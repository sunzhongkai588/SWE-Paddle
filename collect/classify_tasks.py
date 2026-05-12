#!/usr/bin/env python3
"""
Classify instances by type and split into tracks.

Reads instances JSONL, classifies each instance by task title + patch characteristics,
outputs track_a_bugfix.jsonl, track_b_testgen.jsonl, track_c_feature.jsonl.

Usage:
    python classify_tasks.py [--input instances_6to9_raw.jsonl] [--suffix _6to9]
"""

import json
import os
import sys

DATASET_DIR = "/home/sunzhongkai/disk/paddleswe/dataset"


def classify_task(task_title: str, repo: str, has_code: bool, has_test: bool) -> tuple[str, str]:
    """
    Classify a task into (track, task_type).
    Returns: (track, task_type)
      track: "A" (BugFix), "B" (TestGen), "C" (FeatureImpl), "X" (excluded)
      task_type: BF, TG_operator, TG_module, FI, FE, UNKNOWN
    """
    title = task_title.lower()

    # Rule 1: FastDeploy test-only tasks
    if repo == "PaddlePaddle/FastDeploy":
        if has_test and not has_code:
            if "自定义算子" in task_title or "算子" in task_title:
                return "B", "TG_operator"
            else:
                return "B", "TG_module"
        elif has_test and has_code:
            return "B", "TG_operator"

    # Rule 2: Bug Fix (keywords)
    bug_keywords = ["修复", "fix", "0-size", "0-Size", "精度", "precision",
                    "bug", "error", "crash", "问题修复"]
    if any(kw.lower() in title for kw in bug_keywords):
        if has_code and has_test:
            return "A", "BF"
        elif has_code and not has_test:
            return "A", "BF"
        else:
            return "X", "BF_no_code"

    # Rule 3: Feature Implementation (keywords)
    feature_keywords = ["新增", "实现", "开发", "添加", "支持", "implement", "add"]
    if any(kw in task_title for kw in feature_keywords):
        if has_code and has_test:
            return "C", "FI"
        elif has_code:
            return "C", "FI"
        else:
            return "X", "FI_no_code"

    # Rule 4: Feature Enhancement (keywords)
    enhance_keywords = ["优化", "增强", "改进", "完善", "升级", "enhance", "improve"]
    if any(kw in task_title for kw in enhance_keywords):
        if has_code:
            return "C", "FE"
        else:
            return "X", "FE_no_code"

    # Default: classify by patch characteristics
    if has_code and has_test:
        return "A", "BF"
    elif has_test and not has_code:
        return "B", "TG_other"
    elif has_code and not has_test:
        return "X", "UNKNOWN_code_only"
    else:
        return "X", "UNKNOWN"


def main():
    input_file = "instances_6to9_raw.jsonl"
    suffix = "_6to9"

    args = sys.argv[1:]
    while args:
        if args[0] == "--input":
            input_file = args[1]
            args = args[2:]
        elif args[0] == "--suffix":
            suffix = args[1]
            args = args[2:]
        else:
            args = args[1:]

    # Load instances
    instances_path = os.path.join(DATASET_DIR, input_file)
    with open(instances_path) as f:
        instances = [json.loads(line) for line in f]

    print(f"Loaded {len(instances)} instances from {input_file}", file=sys.stderr)

    # Classify each instance
    track_a = []
    track_b = []
    track_c = []
    excluded = []

    for inst in instances:
        task_title = inst.get("task_title", inst.get("pr_title", ""))

        track, task_type = classify_task(
            task_title=task_title,
            repo=inst["repo"],
            has_code=inst["has_code_patch"],
            has_test=inst["has_test_patch"],
        )

        inst["track"] = track
        inst["task_type"] = task_type

        if track == "A":
            inst["eval_method"] = "pass_at_1"
            track_a.append(inst)
        elif track == "B":
            inst["eval_method"] = "coverage_mutation"
            track_b.append(inst)
        elif track == "C":
            inst["eval_method"] = "pass_at_1"
            track_c.append(inst)
        else:
            inst["eval_method"] = "none"
            excluded.append(inst)

    # Output
    def write_jsonl(path, data):
        with open(path, "w") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    write_jsonl(os.path.join(DATASET_DIR, f"track_a_bugfix{suffix}.jsonl"), track_a)
    write_jsonl(os.path.join(DATASET_DIR, f"track_b_testgen{suffix}.jsonl"), track_b)
    write_jsonl(os.path.join(DATASET_DIR, f"track_c_feature{suffix}.jsonl"), track_c)
    write_jsonl(os.path.join(DATASET_DIR, f"excluded{suffix}.jsonl"), excluded)

    # Statistics
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"Classification Results:", file=sys.stderr)
    print(f"  Track A (Bug Fix):       {len(track_a)}", file=sys.stderr)
    print(f"  Track B (Test Gen):      {len(track_b)}", file=sys.stderr)
    print(f"  Track C (Feature Impl):  {len(track_c)}", file=sys.stderr)
    print(f"  Excluded:                {len(excluded)}", file=sys.stderr)

    # Per-track breakdown
    from collections import Counter

    print(f"\nTrack A breakdown:", file=sys.stderr)
    a_types = Counter(i["task_type"] for i in track_a)
    for tt, c in a_types.most_common():
        print(f"  {tt}: {c}", file=sys.stderr)

    print(f"\nTrack B breakdown:", file=sys.stderr)
    b_types = Counter(i["task_type"] for i in track_b)
    for tt, c in b_types.most_common():
        print(f"  {tt}: {c}", file=sys.stderr)

    print(f"\nTrack C breakdown:", file=sys.stderr)
    c_types = Counter(i["task_type"] for i in track_c)
    for tt, c in c_types.most_common():
        print(f"  {tt}: {c}", file=sys.stderr)

    print(f"\nExcluded breakdown:", file=sys.stderr)
    x_types = Counter(i["task_type"] for i in excluded)
    for tt, c in x_types.most_common():
        print(f"  {tt}: {c}", file=sys.stderr)

    # Per-edition stats
    print(f"\nPer-edition distribution:", file=sys.stderr)
    for track_name, track_data in [("A", track_a), ("B", track_b), ("C", track_c)]:
        editions = Counter(i.get("hackathon_edition", "?") for i in track_data)
        print(f"  Track {track_name}: {dict(sorted(editions.items()))}", file=sys.stderr)


if __name__ == "__main__":
    main()
