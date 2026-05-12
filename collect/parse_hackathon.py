#!/usr/bin/env python3
"""
Step 1: Parse hackathon task tables from GitHub issues.
Extracts task info (task_number, difficulty, title, PR URLs, status, assignee).
"""

import json
import re
import ssl
import sys
import urllib.request
import os

PROXY = "http://agent.baidu.com:8891"
os.environ["https_proxy"] = PROXY
os.environ["http_proxy"] = PROXY

if os.environ.get("SSL_NO_VERIFY"):
    ssl._create_default_https_context = ssl._create_unverified_context

# Hackathon 9th: 个人挑战赛 issues
HACKATHON_9TH_ISSUES = {
    "个人挑战赛": 74773,
    "个人挑战赛-加赛": 76333,
}


def fetch_issue_body(repo: str, issue_number: int) -> str:
    """Fetch issue body from GitHub API."""
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github.v3+json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    return data.get("body", "")


def parse_task_table(body: str, hackathon_edition: str, track: str) -> list[dict]:
    """Parse markdown table rows to extract task info."""
    tasks = []

    # Match table rows: | 序号 | 难度 | 任务标题 | 队伍名称/状态/PR | 完成队伍 |
    # Each row may span multiple lines due to <br> tags
    # Strategy: split by table row pattern
    row_pattern = re.compile(
        r'^\|\s*(\d+)\s*\|'      # 序号
        r'\s*([\d.]+🌟?)\s*\|'    # 难度
        r'\s*(.*?)\s*\|'          # 任务标题
        r'\s*(.*?)\s*\|'          # 队伍名称/状态/PR
        r'\s*(.*?)\s*\|',         # 完成队伍
        re.MULTILINE
    )

    for m in row_pattern.finditer(body):
        task_number = int(m.group(1))
        difficulty_raw = m.group(2).replace("🌟", "").strip()
        try:
            difficulty = float(difficulty_raw)
        except ValueError:
            difficulty = 0.0
        title_cell = m.group(3).strip()
        status_cell = m.group(4).strip()
        completer_cell = m.group(5).strip()

        # Extract task title and community link from title cell
        title_match = re.search(r'\[([^\]]+)\]\((https?://[^\)]+)\)', title_cell)
        task_title = title_match.group(1) if title_match else title_cell
        community_url = title_match.group(2) if title_match else ""

        # Extract status
        status = "未知"
        if "完成任务" in status_cell:
            status = "完成任务"
        elif "提交PR" in status_cell:
            status = "提交PR"
        elif "报名" in status_cell or "@" in status_cell:
            status = "报名"

        # Extract PR URLs from status cell
        pr_urls = []
        pr_pattern = re.compile(r'\[#(\d+)\]\((https://github\.com/([^/]+/[^/]+)/pull/(\d+))\)')
        for pm in pr_pattern.finditer(status_cell):
            pr_urls.append({
                "pr_number": int(pm.group(1)),
                "url": pm.group(2),
                "repo": pm.group(3),
            })

        # Extract assignees
        assignees = re.findall(r'@([\w-]+)', status_cell)

        # Extract completers
        completers = re.findall(r'@([\w-]+)', completer_cell)

        tasks.append({
            "instance_id": f"hackathon_{hackathon_edition}_{task_number}",
            "hackathon_edition": hackathon_edition,
            "track": track,
            "task_number": task_number,
            "difficulty": difficulty,
            "task_title": task_title,
            "community_url": community_url,
            "status": status,
            "pr_urls": pr_urls,
            "assignees": assignees,
            "completers": completers,
        })

    return tasks


def main():
    all_tasks = []

    for track, issue_number in HACKATHON_9TH_ISSUES.items():
        print(f"Fetching issue #{issue_number} ({track})...", file=sys.stderr)
        body = fetch_issue_body("PaddlePaddle/Paddle", issue_number)

        tasks = parse_task_table(body, "9th", track)
        print(f"  Parsed {len(tasks)} tasks", file=sys.stderr)
        all_tasks.extend(tasks)

    # Filter: only completed tasks with merged PRs
    completed = [t for t in all_tasks if t["status"] == "完成任务"]
    with_pr = [t for t in completed if len(t["pr_urls"]) > 0]

    print(f"\nTotal tasks parsed: {len(all_tasks)}", file=sys.stderr)
    print(f"Completed tasks: {len(completed)}", file=sys.stderr)
    print(f"Completed with PR: {len(with_pr)}", file=sys.stderr)

    # Group by repo
    repo_counts = {}
    for t in with_pr:
        for pr in t["pr_urls"]:
            repo = pr["repo"]
            repo_counts[repo] = repo_counts.get(repo, 0) + 1
    print(f"\nPR count by repo:", file=sys.stderr)
    for repo, count in sorted(repo_counts.items(), key=lambda x: -x[1]):
        print(f"  {repo}: {count}", file=sys.stderr)

    REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATASET_DIR = os.path.join(REPO_ROOT, "dataset")

    # Output all tasks as JSONL
    output_path = os.path.join(DATASET_DIR, "tasks_9th.jsonl")
    with open(output_path, "w") as f:
        for t in all_tasks:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"\nWritten {len(all_tasks)} tasks to {output_path}", file=sys.stderr)

    # Also output filtered completed tasks
    output_path_completed = os.path.join(DATASET_DIR, "tasks_9th_completed.jsonl")
    with open(output_path_completed, "w") as f:
        for t in with_pr:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")
    print(f"Written {len(with_pr)} completed tasks to {output_path_completed}", file=sys.stderr)


if __name__ == "__main__":
    main()
