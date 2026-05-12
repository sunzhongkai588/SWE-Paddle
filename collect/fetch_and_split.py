#!/usr/bin/env python3
"""
Step 2: Fetch detailed task descriptions from PaddlePaddle/community repo.
Step 3: Fetch PR info (base_commit, diff, metadata) from GitHub API.
Step 4: Split diff into code_patch and test_patch.

Reads tasks_9th_completed.jsonl, enriches each task, outputs dataset.jsonl.
"""

import json
import os
import re
import ssl
import sys
import time
import urllib.request
from urllib.parse import quote

PROXY = "http://agent.baidu.com:8891"
os.environ["https_proxy"] = PROXY
os.environ["http_proxy"] = PROXY
if os.environ.get("SSL_NO_VERIFY"):
    ssl._create_default_https_context = ssl._create_unverified_context

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET_DIR = os.path.join(REPO_ROOT, "dataset")

# Test file path patterns for Paddle ecosystem
TEST_PATH_PATTERNS = [
    re.compile(r'^test/'),
    re.compile(r'^tests/'),
    re.compile(r'test_[^/]*\.(py|cc|cu)$'),
    re.compile(r'[^/]*_test\.(py|cc|cu)$'),
]


def is_test_file(filepath: str) -> bool:
    """Check if a file path is a test file."""
    return any(p.search(filepath) for p in TEST_PATH_PATTERNS)


def fetch_url(url: str, max_retries: int = 3) -> bytes:
    """Fetch URL with retries."""
    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(url, headers={
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "PaddleSWE-Collector/1.0",
            })
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read()
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"  Retry {attempt+1}/{max_retries} after {wait}s: {e}", file=sys.stderr)
                time.sleep(wait)
            else:
                raise


def fetch_json(url: str) -> dict:
    """Fetch JSON from URL."""
    return json.loads(fetch_url(url).decode())


# ===================== Step 2: Fetch task descriptions =====================

def fetch_task_descriptions() -> dict[str, str]:
    """
    Fetch the task description markdown files from community repo.
    Returns a dict mapping community_url anchor -> full description text.
    """
    # Known markdown files for hackathon 9th
    md_files = [
        "hackathon/hackathon_9th/【Hackathon_9th】个人挑战赛—框架开发任务合集.md",
        "hackathon/hackathon_9th/【Hackathon_9th】个人挑战赛—FastDeploy任务合集.md",
        "hackathon/hackathon_9th/【Hackathon_9th】个人挑战赛—科学计算任务合集.md",
    ]

    all_sections = {}

    for md_path in md_files:
        encoded_path = quote(md_path, safe="/")
        url = f"https://raw.githubusercontent.com/PaddlePaddle/community/master/{encoded_path}"
        print(f"  Fetching {md_path}...", file=sys.stderr)
        try:
            content = fetch_url(url).decode("utf-8")
        except Exception as e:
            print(f"  WARNING: Failed to fetch {md_path}: {e}", file=sys.stderr)
            continue

        # Split by ### NO.X headers
        sections = re.split(r'(?=^### NO\.\d+)', content, flags=re.MULTILINE)
        for section in sections:
            # Extract NO.X number
            m = re.match(r'^### NO\.(\d+)\s+(.*)', section)
            if not m:
                continue
            task_no = int(m.group(1))
            all_sections[task_no] = section.strip()

    return all_sections


def extract_description_parts(full_text: str) -> dict:
    """
    Extract structured parts from a task description.
    Returns: {problem_statement_full, problem_statement_minimal, acceptance_criteria, hints_text}
    """
    result = {
        "problem_statement_full": full_text,
        "problem_statement_minimal": "",
        "acceptance_criteria": "",
        "hints_text": "",
    }

    # Extract title line
    title_match = re.match(r'^### NO\.\d+\s+(.*)', full_text)
    title = title_match.group(1).strip() if title_match else ""

    # Extract sections
    desc_match = re.search(r'\*\*详细描述[：:]\*\*\s*\n(.*?)(?=\*\*验收说明|\*\*技术要求|\*\*参考资料|$)',
                           full_text, re.DOTALL)
    accept_match = re.search(r'\*\*验收说明[：:]\*\*\s*\n(.*?)(?=\*\*技术要求|\*\*参考资料|$)',
                             full_text, re.DOTALL)
    tech_match = re.search(r'\*\*技术要求[：:]\*\*\s*\n(.*?)(?=\*\*参考资料|$)',
                           full_text, re.DOTALL)
    ref_match = re.search(r'\*\*参考资料[：:]\*\*\s*\n(.*?)$',
                          full_text, re.DOTALL)

    description = desc_match.group(1).strip() if desc_match else ""
    acceptance = accept_match.group(1).strip() if accept_match else ""
    tech_req = tech_match.group(1).strip() if tech_match else ""
    references = ref_match.group(1).strip() if ref_match else ""

    # Minimal: title + description + acceptance criteria only
    result["problem_statement_minimal"] = f"{title}\n\n{description}\n\n验收说明：\n{acceptance}".strip()
    result["acceptance_criteria"] = acceptance
    # Hints: tech requirements + references
    result["hints_text"] = f"技术要求：\n{tech_req}\n\n参考资料：\n{references}".strip()

    return result


# ===================== Step 3: Fetch PR info =====================

def fetch_pr_info(repo: str, pr_number: int) -> dict:
    """Fetch PR metadata and diff from GitHub API."""
    # Fetch PR metadata
    api_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
    pr_data = fetch_json(api_url)

    info = {
        "pr_number": pr_number,
        "repo": repo,
        "title": pr_data.get("title", ""),
        "merged": pr_data.get("merged", False),
        "state": pr_data.get("state", ""),
        "base_commit": pr_data.get("base", {}).get("sha", ""),
        "merge_commit_sha": pr_data.get("merge_commit_sha", ""),
        "additions": pr_data.get("additions", 0),
        "deletions": pr_data.get("deletions", 0),
        "changed_files": pr_data.get("changed_files", 0),
        "created_at": pr_data.get("created_at", ""),
        "merged_at": pr_data.get("merged_at", ""),
    }

    # Fetch diff
    diff_url = f"https://github.com/{repo}/pull/{pr_number}.diff"
    try:
        diff_content = fetch_url(diff_url).decode("utf-8", errors="replace")
        info["full_diff"] = diff_content
    except Exception as e:
        print(f"  WARNING: Failed to fetch diff for {repo}#{pr_number}: {e}", file=sys.stderr)
        info["full_diff"] = ""

    # Fetch file list
    files_url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files?per_page=100"
    try:
        files_data = fetch_json(files_url)
        info["files"] = [
            {
                "filename": f["filename"],
                "status": f.get("status", ""),
                "additions": f.get("additions", 0),
                "deletions": f.get("deletions", 0),
                "patch": f.get("patch", ""),
            }
            for f in files_data
        ]
    except Exception as e:
        print(f"  WARNING: Failed to fetch files for {repo}#{pr_number}: {e}", file=sys.stderr)
        info["files"] = []

    return info


# ===================== Step 4: Split patch =====================

def split_patch(full_diff: str) -> tuple[str, str]:
    """
    Split a unified diff into code_patch and test_patch.
    Returns (code_patch, test_patch).
    """
    if not full_diff:
        return "", ""

    # Split by file boundaries: "diff --git a/..."
    file_diffs = re.split(r'(?=^diff --git )', full_diff, flags=re.MULTILINE)

    code_parts = []
    test_parts = []

    for fd in file_diffs:
        if not fd.strip():
            continue

        # Extract filename from "diff --git a/path b/path"
        m = re.match(r'diff --git a/(.*?) b/(.*?)(?:\n|$)', fd)
        if not m:
            code_parts.append(fd)
            continue

        filepath = m.group(2)  # use the b/ path

        if is_test_file(filepath):
            test_parts.append(fd)
        else:
            code_parts.append(fd)

    return "".join(code_parts), "".join(test_parts)


def count_patch_loc(patch: str) -> int:
    """Count lines of code changes (additions + deletions) in a patch."""
    loc = 0
    for line in patch.split("\n"):
        if line.startswith("+") and not line.startswith("+++"):
            loc += 1
        elif line.startswith("-") and not line.startswith("---"):
            loc += 1
    return loc


def detect_languages(files: list[dict]) -> list[str]:
    """Detect programming languages from file list."""
    exts = set()
    for f in files:
        name = f["filename"]
        if name.endswith(".py"):
            exts.add("python")
        elif name.endswith(".cc") or name.endswith(".cpp") or name.endswith(".h"):
            exts.add("cpp")
        elif name.endswith(".cu") or name.endswith(".cuh"):
            exts.add("cuda")
        elif name.endswith(".cmake") or name == "CMakeLists.txt":
            exts.add("cmake")
    return sorted(exts)


# ===================== Main pipeline =====================

def main():
    # Load completed tasks
    tasks_path = os.path.join(DATASET_DIR, "tasks_9th_completed.jsonl")
    with open(tasks_path) as f:
        tasks = [json.loads(line) for line in f]

    print(f"Loaded {len(tasks)} completed tasks", file=sys.stderr)

    # Step 2: Fetch task descriptions
    print("\n=== Step 2: Fetching task descriptions ===", file=sys.stderr)
    descriptions = fetch_task_descriptions()
    print(f"  Fetched descriptions for {len(descriptions)} tasks", file=sys.stderr)

    # Step 3 & 4: For each task, fetch PR info and split patches
    print("\n=== Step 3 & 4: Fetching PR info and splitting patches ===", file=sys.stderr)

    instances = []
    for i, task in enumerate(tasks):
        task_no = task["task_number"]
        print(f"\n[{i+1}/{len(tasks)}] Task NO.{task_no}: {task['task_title']}", file=sys.stderr)

        # Get description
        desc_parts = {}
        if task_no in descriptions:
            desc_parts = extract_description_parts(descriptions[task_no])
        else:
            desc_parts = {
                "problem_statement_full": task["task_title"],
                "problem_statement_minimal": task["task_title"],
                "acceptance_criteria": "",
                "hints_text": "",
            }

        # Process each PR (most tasks have 1 PR, some have multiple)
        for pr_info_raw in task["pr_urls"]:
            repo = pr_info_raw["repo"]
            pr_number = pr_info_raw["pr_number"]

            print(f"  Fetching {repo}#{pr_number}...", file=sys.stderr)
            time.sleep(0.5)  # Rate limiting

            try:
                pr_info = fetch_pr_info(repo, pr_number)
            except Exception as e:
                print(f"  ERROR: Failed to fetch PR: {e}", file=sys.stderr)
                continue

            if not pr_info["merged"]:
                print(f"  SKIP: PR not merged", file=sys.stderr)
                continue

            # Split patch
            code_patch, test_patch = split_patch(pr_info["full_diff"])
            code_loc = count_patch_loc(code_patch)
            test_loc = count_patch_loc(test_patch)

            # Classify test/code files
            code_files = [f for f in pr_info["files"] if not is_test_file(f["filename"])]
            test_files = [f for f in pr_info["files"] if is_test_file(f["filename"])]

            has_code = len(code_patch.strip()) > 0
            has_test = len(test_patch.strip()) > 0

            print(f"    code_files={len(code_files)} test_files={len(test_files)} "
                  f"code_loc={code_loc} test_loc={test_loc} "
                  f"has_code={has_code} has_test={has_test}", file=sys.stderr)

            # Build instance
            instance_id = f"{repo.replace('/', '__')}-{pr_number}"
            instance = {
                # SWE-bench standard fields
                "instance_id": instance_id,
                "repo": repo,
                "base_commit": pr_info["base_commit"],
                "patch": code_patch,
                "test_patch": test_patch,
                "problem_statement": desc_parts["problem_statement_minimal"],
                "hints_text": desc_parts["hints_text"],
                "FAIL_TO_PASS": [],  # To be filled by Step 5 (Docker validation)
                "PASS_TO_PASS": [],  # To be filled by Step 5
                "created_at": pr_info["created_at"],

                # PaddleSWE extensions
                "hackathon_edition": task["hackathon_edition"],
                "task_number": task_no,
                "task_category": "",
                "difficulty": task["difficulty"],
                "problem_statement_full": desc_parts["problem_statement_full"],
                "acceptance_criteria": desc_parts["acceptance_criteria"],
                "gold_patch_loc": code_loc,
                "gold_patch_files": len(code_files),
                "test_patch_loc": test_loc,
                "test_patch_files": len(test_files),
                "language_mix": detect_languages(pr_info["files"]),
                "pr_title": pr_info["title"],
                "pr_number": pr_number,
                "merged_at": pr_info["merged_at"],

                # Filtering flags
                "has_code_patch": has_code,
                "has_test_patch": has_test,
            }

            instances.append(instance)

    # Output
    output_path = os.path.join(DATASET_DIR, "instances_9th_raw.jsonl")
    with open(output_path, "w") as f:
        for inst in instances:
            f.write(json.dumps(inst, ensure_ascii=False) + "\n")

    # Statistics
    total = len(instances)
    with_both = sum(1 for i in instances if i["has_code_patch"] and i["has_test_patch"])
    code_only = sum(1 for i in instances if i["has_code_patch"] and not i["has_test_patch"])
    test_only = sum(1 for i in instances if not i["has_code_patch"] and i["has_test_patch"])

    # By repo
    repo_counts = {}
    for i in instances:
        repo_counts[i["repo"]] = repo_counts.get(i["repo"], 0) + 1

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Total instances: {total}", file=sys.stderr)
    print(f"  code + test (usable for SWE-bench): {with_both}", file=sys.stderr)
    print(f"  code only (no test): {code_only}", file=sys.stderr)
    print(f"  test only (no code): {test_only}", file=sys.stderr)
    print(f"\nBy repo:", file=sys.stderr)
    for repo, count in sorted(repo_counts.items(), key=lambda x: -x[1]):
        print(f"  {repo}: {count}", file=sys.stderr)
    print(f"\nWritten to {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
