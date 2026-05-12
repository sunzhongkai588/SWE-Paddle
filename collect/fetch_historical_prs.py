#!/usr/bin/env python3
"""
Batch fetch PR info and diffs for historical hackathon tasks.
Fetches from GitHub API, splits into code_patch and test_patch.

Usage:
    python fetch_historical_prs.py [--limit 50] [--input tasks_6to9.jsonl] [--output instances_6to9_raw.jsonl]
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
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_DIR = os.path.join(REPO_ROOT, "dataset")

TEST_PATH_PATTERNS = [
    re.compile(r'^test/'),
    re.compile(r'^tests/'),
    re.compile(r'test_[^/]*\.(py|cc|cu)$'),
    re.compile(r'[^/]*_test\.(py|cc|cu)$'),
    re.compile(r'^python/paddle/fluid/tests/'),
]


def github_get(url: str) -> Optional[str]:
    """Make authenticated GitHub API/raw request."""
    headers = {
        "Authorization": f"token {GH_TOKEN}",
        "User-Agent": "PaddleSWE-Crawler",
    }
    proxy_handler = urllib.request.ProxyHandler({"https": PROXY})
    opener = urllib.request.build_opener(proxy_handler)
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(req, timeout=60) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  ERROR: {url} → {e}", file=sys.stderr)
        return None


def github_get_json(url: str) -> Optional[dict]:
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


def is_test_file(path: str) -> bool:
    return any(p.search(path) for p in TEST_PATH_PATTERNS)


def split_diff(diff_text: str) -> tuple[str, str, int, int]:
    """Split a unified diff into code_patch and test_patch."""
    code_parts = []
    test_parts = []
    current_file = None
    current_block = []

    for line in diff_text.split("\n"):
        if line.startswith("diff --git"):
            # Flush previous block
            if current_file and current_block:
                block_text = "\n".join(current_block) + "\n"
                if is_test_file(current_file):
                    test_parts.append(block_text)
                else:
                    code_parts.append(block_text)
            # Start new block
            m = re.search(r' b/(.+)$', line)
            current_file = m.group(1) if m else ""
            current_block = [line]
        else:
            current_block.append(line)

    # Flush last block
    if current_file and current_block:
        block_text = "\n".join(current_block) + "\n"
        if is_test_file(current_file):
            test_parts.append(block_text)
        else:
            code_parts.append(block_text)

    code_patch = "".join(code_parts)
    test_patch = "".join(test_parts)

    # Count LOC (added lines)
    code_loc = sum(1 for l in code_patch.split("\n") if l.startswith("+") and not l.startswith("+++"))
    test_loc = sum(1 for l in test_patch.split("\n") if l.startswith("+") and not l.startswith("+++"))

    return code_patch, test_patch, code_loc, test_loc


def fetch_pr(repo: str, pr_num: int, task: dict) -> Optional[dict]:
    """Fetch a single PR's info and diff."""
    # Get PR metadata
    url = f"https://api.github.com/repos/{repo}/pulls/{pr_num}"
    pr_data = github_get_json(url)
    if not pr_data:
        return None

    if not pr_data.get("merged"):
        return None  # Skip unmerged PRs

    # Get diff
    diff_url = f"https://github.com/{repo}/pull/{pr_num}.diff"
    diff_text = github_get(diff_url)
    if not diff_text:
        return None

    # Split patch
    code_patch, test_patch, code_loc, test_loc = split_diff(diff_text)

    instance_id = f"{repo.replace('/', '__')}-{pr_num}"

    return {
        "instance_id": instance_id,
        "repo": repo,
        "pr_number": pr_num,
        "pr_title": pr_data.get("title", ""),
        "base_commit": pr_data.get("base", {}).get("sha", ""),
        "merged_at": pr_data.get("merged_at", ""),
        "code_patch": code_patch,
        "test_patch": test_patch,
        "gold_patch_loc": code_loc,
        "test_patch_loc": test_loc,
        "has_code_patch": code_loc > 0,
        "has_test_patch": test_loc > 0,
        "changed_files": pr_data.get("changed_files", 0),
        "additions": pr_data.get("additions", 0),
        "deletions": pr_data.get("deletions", 0),
        # Task metadata
        "task_number": task.get("task_number"),
        "task_title": task.get("task_title", ""),
        "hackathon_edition": task.get("hackathon_edition", ""),
        "community_file": task.get("community_file", ""),
        "difficulty": task.get("difficulty", ""),
    }


def main():
    if not GH_TOKEN:
        print("ERROR: Set GH_TOKEN", file=sys.stderr)
        sys.exit(1)

    limit = 999
    input_file = "tasks_6to9.jsonl"
    output_file = "instances_6to9_raw.jsonl"

    args = sys.argv[1:]
    while args:
        if args[0] == "--limit":
            limit = int(args[1])
            args = args[2:]
        elif args[0] == "--input":
            input_file = args[1]
            args = args[2:]
        elif args[0] == "--output":
            output_file = args[1]
            args = args[2:]
        else:
            args = args[1:]

    # Load tasks
    tasks_path = os.path.join(DATASET_DIR, input_file)
    with open(tasks_path) as f:
        tasks = [json.loads(l) for l in f]

    # Extract unique PRs from Paddle and FastDeploy with task context
    SUPPORTED_REPOS = {"PaddlePaddle/Paddle", "PaddlePaddle/FastDeploy"}
    pr_tasks = []  # (repo, pr_num, task)
    seen_prs = set()
    for task in tasks:
        for url in task.get("pr_urls", []):
            m = re.match(r'https://github\.com/(PaddlePaddle/(?:Paddle|FastDeploy))/pull/(\d+)', url)
            if m:
                repo = m.group(1)
                pr_num = int(m.group(2))
                key = (repo, pr_num)
                if key not in seen_prs:
                    seen_prs.add(key)
                    pr_tasks.append((repo, pr_num, task))

    print(f"Found {len(pr_tasks)} unique PRs to fetch (Paddle + FastDeploy)", file=sys.stderr)
    print(f"Limit: {limit}", file=sys.stderr)

    # Fetch PRs
    instances = []
    skipped_unmerged = 0

    output_path = os.path.join(DATASET_DIR, output_file)
    with open(output_path, "w") as out_f:
        for i, (repo, pr_num, task) in enumerate(pr_tasks[:limit]):
            if i % 10 == 0:
                print(f"  [{i+1}/{min(len(pr_tasks), limit)}] {repo} PR #{pr_num}...", file=sys.stderr)

            result = fetch_pr(repo, pr_num, task)
            if result is None:
                skipped_unmerged += 1
                continue

            instances.append(result)
            out_f.write(json.dumps(result, ensure_ascii=False) + "\n")
            out_f.flush()

            time.sleep(0.3)  # Rate limit

    # Summary
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Results:", file=sys.stderr)
    print(f"  Total fetched: {len(instances)}", file=sys.stderr)
    print(f"  Skipped (not merged/error): {skipped_unmerged}", file=sys.stderr)
    print(f"  Has code+test: {sum(1 for i in instances if i['has_code_patch'] and i['has_test_patch'])}", file=sys.stderr)
    print(f"  Code only: {sum(1 for i in instances if i['has_code_patch'] and not i['has_test_patch'])}", file=sys.stderr)
    print(f"  Test only: {sum(1 for i in instances if not i['has_code_patch'] and i['has_test_patch'])}", file=sys.stderr)

    # Per-repo breakdown
    from collections import Counter
    repo_counts = Counter(i["repo"] for i in instances)
    for r, c in repo_counts.most_common():
        print(f"  {r}: {c}", file=sys.stderr)

    print(f"\nWritten to: {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
