#!/usr/bin/env python3
"""
Crawl historical hackathon (4th~8th, 10th) task tables from GitHub Issues.
Extracts completed tasks and their PR URLs.

Usage:
    python crawl_historical.py [--edition 4th]
    python crawl_historical.py --all
"""

import json
import os
import re
import ssl
import sys
import time
import urllib.request
from typing import Optional

ssl._create_default_https_context = ssl._create_unverified_context

GH_TOKEN = os.environ.get("GH_TOKEN", "")
PROXY = os.environ.get("https_proxy", "http://agent.baidu.com:8891")
OUTPUT_DIR = "/home/sunzhongkai/disk/paddleswe/dataset"

# Overview issues per edition (个人挑战赛, from user-provided correct numbers)
# Only 6th+ per user instruction
HACKATHON_ISSUES = {
    "6th": {
        "PaddlePaddle/Paddle": [
            62905,  # 开源贡献个人挑战赛
        ],
    },
    "7th": {
        "PaddlePaddle/Paddle": [
            68244,  # 个人挑战赛
        ],
    },
    "8th": {
        "PaddlePaddle/Paddle": [
            71310,  # 个人挑战赛
        ],
    },
    "9th": {
        "PaddlePaddle/Paddle": [
            74773,  # 个人挑战赛
        ],
    },
}


def github_get(url: str) -> Optional[dict]:
    """Make authenticated GitHub API request."""
    headers = {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "PaddleSWE-Crawler",
    }
    proxy_handler = urllib.request.ProxyHandler({"https": PROXY})
    opener = urllib.request.build_opener(proxy_handler)

    req = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  ERROR: {url} → {e}", file=sys.stderr)
        return None


def parse_issue_body_for_tasks(body: str, repo: str, edition: str) -> list:
    """Parse issue body (markdown table) to extract tasks and PR URLs."""
    tasks = []

    # Pattern 1: markdown table rows with PR links
    # | NO.X | title | ... | PR link | status |
    # Various table formats across editions
    lines = body.split("\n")

    for line in lines:
        if "|" not in line:
            continue
        cells = [c.strip() for c in line.split("|")]
        if len(cells) < 4:
            continue

        # Try to find task number
        task_num = None
        for cell in cells:
            m = re.search(r"(?:NO\.?|#)\s*(\d+)", cell, re.IGNORECASE)
            if m:
                task_num = int(m.group(1))
                break

        if task_num is None:
            continue

        # Only keep tasks marked as completed (badge: "完成任务")
        if "完成任务" not in line:
            continue

        # Find PR URLs in the row
        pr_urls = re.findall(
            r"https://github\.com/([^/]+/[^/]+)/pull/(\d+)",
            line,
        )

        status = "completed"

        # Extract community URL and real task_title from markdown link
        # Format: [任务标题](https://github.com/PaddlePaddle/community/blob/master/hackathon/...)
        community_match = re.search(
            r'\[([^\]]+)\]\((https://github\.com/PaddlePaddle/community/[^)]+)\)',
            line,
        )
        title = ""
        community_url = ""
        community_file = ""
        if community_match:
            title = community_match.group(1).strip()
            community_url = community_match.group(2)
            # Extract relative file path from URL (decode percent-encoding)
            # e.g. .../blob/master/hackathon/hackathon_9th/【...】.md#anchor
            file_match = re.search(r'/blob/master/(hackathon/[^#]+)', community_url)
            if file_match:
                from urllib.parse import unquote
                community_file = unquote(file_match.group(1))

        # Fallback title extraction if no community link
        if not title:
            for cell in cells[1:]:
                if len(cell) > 5 and not cell.startswith("http") and not re.match(r"^[✅🚧❌]", cell):
                    if not re.match(r"^\d+$", cell) and "pull/" not in cell:
                        title = cell
                        break

        if pr_urls:
            tasks.append({
                "task_number": task_num,
                "task_title": title[:200],
                "community_url": community_url,
                "community_file": community_file,
                "pr_urls": [f"https://github.com/{r}/pull/{p}" for r, p in pr_urls] if pr_urls else [],
                "pr_repos": [r for r, _ in pr_urls] if pr_urls else [],
                "status": status,
                "hackathon_edition": edition,
                "source_repo": repo,
            })

    return tasks


def parse_issue_comments_for_tasks(comments: list, repo: str, edition: str) -> list:
    """Some issues have tasks in comments rather than body."""
    all_tasks = []
    for comment in comments:
        body = comment.get("body", "")
        tasks = parse_issue_body_for_tasks(body, repo, edition)
        all_tasks.extend(tasks)
    return all_tasks


def crawl_edition(edition: str) -> list:
    """Crawl all overview issues for a given hackathon edition."""
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Crawling hackathon {edition}", file=sys.stderr)

    all_tasks = []
    repos = HACKATHON_ISSUES.get(edition, {})

    for repo, issue_nums in repos.items():
        for issue_num in issue_nums:
            print(f"  Fetching {repo}#{issue_num}...", file=sys.stderr)

            # Get issue body
            url = f"https://api.github.com/repos/{repo}/issues/{issue_num}"
            data = github_get(url)
            if not data:
                continue

            body = data.get("body", "")
            tasks = parse_issue_body_for_tasks(body, repo, edition)
            print(f"    Body: found {len(tasks)} tasks", file=sys.stderr)
            all_tasks.extend(tasks)

            # Also check comments (some issues have tables in comments)
            comments_url = f"{url}/comments?per_page=100"
            comments = github_get(comments_url)
            if comments and isinstance(comments, list):
                comment_tasks = parse_issue_comments_for_tasks(comments, repo, edition)
                if comment_tasks:
                    print(f"    Comments: found {len(comment_tasks)} additional tasks", file=sys.stderr)
                    all_tasks.extend(comment_tasks)

            time.sleep(0.5)  # Rate limit courtesy

    # Deduplicate by task_number within same edition
    seen = set()
    deduped = []
    for t in all_tasks:
        key = (edition, t["task_number"])
        if key not in seen:
            seen.add(key)
            deduped.append(t)

    print(f"\n  Total for {edition}: {len(deduped)} tasks "
          f"({sum(1 for t in deduped if t['pr_urls'])} with PRs)",
          file=sys.stderr)

    return deduped


def main():
    if not GH_TOKEN:
        print("ERROR: Set GH_TOKEN environment variable", file=sys.stderr)
        sys.exit(1)

    # Parse args
    editions = list(HACKATHON_ISSUES.keys())
    if len(sys.argv) > 1:
        if sys.argv[1] == "--all":
            pass  # use all
        elif sys.argv[1] == "--edition" and len(sys.argv) > 2:
            editions = [sys.argv[2]]
        else:
            print(f"Usage: {sys.argv[0]} [--all | --edition 4th]", file=sys.stderr)
            sys.exit(1)

    all_tasks = []
    for edition in editions:
        tasks = crawl_edition(edition)
        all_tasks.extend(tasks)

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"TOTAL: {len(all_tasks)} tasks across {len(editions)} editions", file=sys.stderr)
    with_prs = [t for t in all_tasks if t["pr_urls"]]
    print(f"  With PR links: {len(with_prs)}", file=sys.stderr)
    completed = [t for t in all_tasks if t["status"] == "completed"]
    print(f"  Marked completed: {len(completed)}", file=sys.stderr)

    # Per-edition stats
    for edition in editions:
        ed_tasks = [t for t in all_tasks if t["hackathon_edition"] == edition]
        ed_prs = [t for t in ed_tasks if t["pr_urls"]]
        print(f"  {edition}: {len(ed_tasks)} tasks, {len(ed_prs)} with PRs", file=sys.stderr)

    # Output
    output_path = os.path.join(OUTPUT_DIR, "tasks_6to9.jsonl")
    with open(output_path, "w") as f:
        for t in all_tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"\nWritten to: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
