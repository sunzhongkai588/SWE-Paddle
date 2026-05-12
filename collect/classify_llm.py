#!/usr/bin/env python3
"""
LLM-judged classification of instances into tracks.
Based on manual review of all 133 instance titles and PR descriptions.
"""

import json

DATASET_DIR = "/home/sunzhongkai/disk/paddleswe/dataset"

# Classification rules based on LLM judgment of each instance's pr_title/task_title:
#
# Track A (Bug Fix): Fixing existing broken functionality
# Track B (Test Gen): Writing tests for existing code (no code changes)
# Track C (Feature): Adding new API/functionality OR enhancing existing ones
# Track X (Excluded): Refactoring/migration (no behavioral change) or unusable data
#
# Sub-types:
#   BF = Bug Fix
#   TG_operator = Test Gen for operator
#   TG_module = Test Gen for module
#   FI = Feature Implementation (new API)
#   FE = Feature Enhancement (enhance existing)
#   RF = Refactoring/Migration
#   PARTIAL = code_only part of multi-PR task

def classify_by_llm(inst: dict) -> tuple[str, str]:
    """Classify based on LLM judgment of content."""
    pr_title = inst.get("pr_title", "").lower()
    task_title = inst.get("task_title", "").lower()
    repo = inst["repo"]
    has_code = inst["has_code_patch"]
    has_test = inst["has_test_patch"]
    pr_num = inst["pr_number"]
    edition = inst.get("hackathon_edition", "")

    # === Track B: FastDeploy test-only ===
    if repo == "PaddlePaddle/FastDeploy" and has_test and not has_code:
        if "自定义算子" in task_title or "自定义算子" in inst.get("task_title", ""):
            return "B", "TG_operator"
        else:
            return "B", "TG_module"

    # === 9th edition NO.1-19: all are 0-Size/precision bug fixes ===
    task_num = inst.get("task_number", 0)
    if edition == "9th" and 1 <= task_num <= 19 and has_code:
        return "A", "BF"

    # === Track A: Bug fixes (0-size, precision) ===
    # 9th edition 0-Size and precision fixes
    bug_indicators = ["fix", "0-size", "0 size", "精度", "precision", "修复", "bug fix"]
    if any(kw in pr_title for kw in bug_indicators):
        # Exclude trivial patches (docs fixes etc)
        if inst.get("gold_patch_loc", 0) < 3:
            return "X", "TRIVIAL"
        # "fix" at end of title after a feature description is not a bug fix
        # e.g. "support kwargs for recompute when use_reentrant == True fix"
        if pr_title.endswith("fix") and ("support" in pr_title or "add" in pr_title):
            pass  # Fall through to feature classification
        elif has_code:
            return "A", "BF"

    # === Excluded: Refactoring/Migration ===
    refactor_indicators = [
        "clean oldir", "remove fleet_executor", "remove dynamic_static",
        "迁移至 pir", "迁移至pir", "从fluid下迁移", "从fluid迁移",
        "fluid下迁移到phi", "revert", "deprecated",
        "dequantize等算子及其kernel实现从fluid",
        "fake_channel_wise", "fake_quantize",
    ]
    if any(kw in pr_title for kw in refactor_indicators):
        return "X", "RF"
    # Also check task_title for migration keywords
    migration_keywords = ["迁移至", "迁移到", "从fluid", "pylayer 机制迁移", "逻辑清理"]
    if any(kw in task_title for kw in migration_keywords):
        return "X", "RF"

    # === Excluded: FastDeploy code-only (build/compilation tasks) ===
    if repo == "PaddlePaddle/FastDeploy" and has_code and not has_test:
        return "X", "BUILD"

    # === Track C: Feature Implementation (new API) ===
    fi_indicators = ["新增", "add ", "为 paddle 新增", "implement"]
    if any(kw in pr_title or kw in task_title for kw in fi_indicators):
        if has_code:
            return "C", "FI"

    # === Track C: Feature Enhancement ===
    fe_indicators = ["功能增强", "功能对齐", "进行功能", "支持复数", "支持 import",
                     "支持动态图", "支持以关键字", "setuptools"]
    if any(kw in task_title for kw in fe_indicators):
        if has_code:
            return "C", "FE"

    # Additional feature indicators in pr_title
    fe_pr_indicators = ["enhance", "support", "add support", "支持"]
    if any(kw in pr_title for kw in fe_pr_indicators):
        if has_code:
            return "C", "FE"

    # === Fallback based on patch characteristics ===
    if has_code and has_test:
        # Has both code and test — likely a feature task
        return "C", "FE"
    elif has_test and not has_code:
        return "B", "TG_other"
    elif has_code and not has_test:
        # code-only: likely partial PR of a multi-PR task
        return "X", "PARTIAL"
    else:
        return "X", "UNKNOWN"


def main():
    with open(f"{DATASET_DIR}/instances_6to9.jsonl") as f:
        instances = [json.loads(line) for line in f]

    track_a, track_b, track_c, excluded = [], [], [], []

    for inst in instances:
        track, task_type = classify_by_llm(inst)
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

    # Write outputs
    def write_jsonl(path, data):
        with open(path, "w") as f:
            for item in data:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    write_jsonl(f"{DATASET_DIR}/track_a_bugfix_6to9.jsonl", track_a)
    write_jsonl(f"{DATASET_DIR}/track_b_testgen_6to9.jsonl", track_b)
    write_jsonl(f"{DATASET_DIR}/track_c_feature_6to9.jsonl", track_c)
    write_jsonl(f"{DATASET_DIR}/excluded_6to9.jsonl", excluded)

    # Also update the main instances file with track info
    write_jsonl(f"{DATASET_DIR}/instances_6to9.jsonl", track_a + track_b + track_c + excluded)

    # Print summary
    import sys
    from collections import Counter
    print(f"Classification Results:", file=sys.stderr)
    print(f"  Track A (Bug Fix):      {len(track_a)}", file=sys.stderr)
    print(f"  Track B (Test Gen):     {len(track_b)}", file=sys.stderr)
    print(f"  Track C (Feature):      {len(track_c)}", file=sys.stderr)
    print(f"  Excluded:               {len(excluded)}", file=sys.stderr)
    print(file=sys.stderr)

    print("Track A:", file=sys.stderr)
    for inst in track_a:
        print(f"  [{inst['task_type']}] {inst['instance_id']} — {inst['pr_title'][:60]}", file=sys.stderr)

    print(f"\nTrack B: {len(track_b)} (TG_operator={sum(1 for i in track_b if i['task_type']=='TG_operator')}, TG_module={sum(1 for i in track_b if i['task_type']=='TG_module')})", file=sys.stderr)

    print(f"\nTrack C breakdown:", file=sys.stderr)
    c_types = Counter(i["task_type"] for i in track_c)
    for tt, cnt in c_types.most_common():
        print(f"  {tt}: {cnt}", file=sys.stderr)

    print(f"\nExcluded breakdown:", file=sys.stderr)
    x_types = Counter(i["task_type"] for i in excluded)
    for tt, cnt in x_types.most_common():
        print(f"  {tt}: {cnt}", file=sys.stderr)
    for inst in excluded:
        print(f"  [{inst['task_type']}] {inst['instance_id']} — {inst['pr_title'][:60]}", file=sys.stderr)


if __name__ == "__main__":
    main()
