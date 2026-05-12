#!/usr/bin/env python3
"""
Extract problem_statement from PaddlePaddle/community hackathon markdown files.
Matches extracted descriptions to tasks in tasks_6to9.jsonl by task_number + edition.

Usage:
    python extract_problem_statement.py
"""

import json
import os
import re
import sys

COMMUNITY_DIR = "/home/sunzhongkai/disk/paddleswe/collect/community/hackathon"
DATASET_DIR = "/home/sunzhongkai/disk/paddleswe/dataset"

# Mapping from edition to the markdown files that contain task descriptions
EDITION_FILES = {
    "6th": [
        "hackathon_6th/【Hackathon 6th】开源贡献个人挑战赛框架开发任务合集.md",
        "hackathon_6th/【Hackathon 6th】开源贡献个人挑战赛科学计算任务合集.md",
        "hackathon_6th/【Hackathon 6th】开源贡献个人挑战赛Paddle2ONNX任务合集.md",
        "hackathon_6th/【Hackathon 6th】开源贡献个人挑战赛合作伙伴任务合集.md",
    ],
    "7th": [
        "hackathon_7th/【Hackathon 7th】个人挑战赛—框架开发任务合集.md",
        "hackathon_7th/【Hackathon 7th】个人挑战赛—套件开发任务合集.md",
        "hackathon_7th/【Hackathon 7th】个人挑战赛—科学计算任务合集.md",
    ],
    "8th": [
        "hackathon_8th/【Hackathon_8th】个人挑战赛—框架开发任务合集.md",
        "hackathon_8th/【Hackathon_8th】个人挑战赛—套件开发任务合集.md",
    ],
    "9th": [
        "hackathon_9th/【Hackathon_9th】个人挑战赛—框架开发任务合集.md",
        "hackathon_9th/【Hackathon_9th】个人挑战赛冲刺赛—任务合集.md",
        "hackathon_9th/【Hackathon_9th】个人挑战赛—套件开发任务合集.md",
        "hackathon_9th/【Hackathon_9th】个人挑战赛—科学计算任务合集.md",
    ],
}


def parse_markdown_tasks(filepath: str) -> dict[int, dict]:
    """
    Parse a hackathon markdown file and extract per-task descriptions.
    Returns: {task_number: {title, description, acceptance, tech_requirements, references}}
    """
    if not os.path.exists(filepath):
        return {}

    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    tasks = {}

    # Strategy: split by ### NO.X headings
    # Handle both "### NO.X title" and "### **NO.X title**" formats
    # Also handle grouped tasks like "**NO.1 - NO.19 API正确性**"

    # First, find grouped task descriptions (shared across multiple task numbers)
    # Pattern: **NO.X - NO.Y description**
    group_pattern = re.compile(
        r'\*\*NO\.(\d+)\s*[-–]\s*NO\.(\d+)\s+(.+?)\*\*',
        re.MULTILINE
    )

    # Find individual task headings
    # Matches: ### NO.X title  or  ### **NO.X title**
    task_heading_pattern = re.compile(
        r'^###\s+\*{0,2}NO\.(\d+)\s+(.+?)\*{0,2}\s*$',
        re.MULTILINE
    )

    # Find all task heading positions
    headings = list(task_heading_pattern.finditer(content))

    for idx, match in enumerate(headings):
        task_num = int(match.group(1))
        task_title = match.group(2).strip()

        # Get content between this heading and the next one
        start = match.end()
        if idx + 1 < len(headings):
            end = headings[idx + 1].start()
        else:
            end = len(content)

        section = content[start:end].strip()

        # Extract structured fields from section
        description = extract_field(section, ["详细描述", "描述"])
        acceptance = extract_field(section, ["验收说明", "提交内容", "提交方式"])
        tech_req = extract_field(section, ["技术要求"])
        references = extract_field(section, ["参考资料", "参考内容"])

        # If this task has no own description, look for group description above it
        if not description:
            # Search backwards from this heading for a group description
            group_desc = find_group_description(content, match.start(), task_num)
            if group_desc:
                description = group_desc.get("description", "")
                if not acceptance:
                    acceptance = group_desc.get("acceptance", "")
                if not tech_req:
                    tech_req = group_desc.get("tech_requirements", "")
                if not references:
                    references = group_desc.get("references", "")

        # Build problem_statement (full version with all fields)
        parts = []
        if task_title:
            parts.append(f"# {task_title}\n")
        if description:
            parts.append(f"## 详细描述\n\n{description}\n")
        if acceptance:
            parts.append(f"## 验收说明\n\n{acceptance}\n")
        if tech_req:
            parts.append(f"## 技术要求\n\n{tech_req}\n")
        if references:
            parts.append(f"## 参考资料\n\n{references}\n")

        problem_statement_full = "\n".join(parts).strip()

        # Minimal version: just title + acceptance criteria
        minimal_parts = [task_title]
        if acceptance:
            minimal_parts.append(f"\n验收说明：{acceptance}")
        problem_statement_minimal = "\n".join(minimal_parts).strip()

        tasks[task_num] = {
            "task_title": task_title,
            "problem_statement_full": problem_statement_full,
            "problem_statement_minimal": problem_statement_minimal,
            "description": description,
            "acceptance": acceptance,
            "tech_requirements": tech_req,
            "references": references,
        }

    return tasks


def extract_field(section: str, field_names: list[str]) -> str:
    """Extract a field value from a section by looking for **field_name：** or **field_name:**"""
    for name in field_names:
        # Pattern: **field_name：** or **field_name:** followed by content until next **field** or end
        pattern = re.compile(
            rf'\*\*{re.escape(name)}[：:]\*\*\s*\n?(.*?)(?=\n\*\*[^*]+[：:]\*\*|\n###|\Z)',
            re.DOTALL
        )
        m = pattern.search(section)
        if m:
            text = m.group(1).strip()
            if text:
                return text
    return ""


def find_group_description(content: str, heading_pos: int, task_num: int) -> dict:
    """
    Look backwards from heading_pos for a group description block like
    **NO.1 - NO.19 API正确性** that covers this task_num.
    """
    # Search the content before this heading for group markers
    before = content[:heading_pos]

    group_pattern = re.compile(
        r'\*\*NO\.(\d+)\s*[-–]\s*NO\.(\d+)\s+.+?\*\*',
        re.MULTILINE
    )

    # Find the last group marker before this heading
    matches = list(group_pattern.finditer(before))
    if not matches:
        return {}

    last_group = matches[-1]
    group_start = int(last_group.group(1))
    group_end = int(last_group.group(2))

    if not (group_start <= task_num <= group_end):
        return {}

    # Extract the group's description section (between group marker and first ### NO.X)
    group_section_start = last_group.end()
    # Find next ### heading after group marker
    next_heading = re.search(r'^###\s+', content[group_section_start:], re.MULTILINE)
    if next_heading:
        group_section = content[group_section_start:group_section_start + next_heading.start()]
    else:
        group_section = content[group_section_start:heading_pos]

    return {
        "description": extract_field(group_section, ["详细描述", "描述"]),
        "acceptance": extract_field(group_section, ["验收说明", "提交内容"]),
        "tech_requirements": extract_field(group_section, ["技术要求"]),
        "references": extract_field(group_section, ["参考资料", "参考内容"]),
    }


def main():
    # Load tasks to match against
    tasks_path = os.path.join(DATASET_DIR, "tasks_6to9.jsonl")
    with open(tasks_path) as f:
        tasks = [json.loads(line) for line in f]

    print(f"Loaded {len(tasks)} tasks from tasks_6to9.jsonl", file=sys.stderr)

    # Parse all markdown files per edition
    all_descriptions = {}  # (relative_filepath, task_num) -> description dict

    for edition, files in EDITION_FILES.items():
        edition_total = 0
        for filename in files:
            filepath = os.path.join(COMMUNITY_DIR, filename)
            if not os.path.exists(filepath):
                print(f"  SKIP (not found): {filename}", file=sys.stderr)
                continue

            parsed = parse_markdown_tasks(filepath)
            # Key by (full relative path under hackathon/, task_num)
            rel_path = f"hackathon/{filename}"
            for task_num, desc in parsed.items():
                key = (rel_path, task_num)
                if key not in all_descriptions:
                    all_descriptions[key] = desc
                    edition_total += 1

        print(f"  {edition}: parsed {edition_total} task descriptions", file=sys.stderr)

    print(f"\nTotal parsed descriptions: {len(all_descriptions)}", file=sys.stderr)

    # Match to tasks and enrich
    matched = 0
    unmatched = 0

    enriched_tasks = []
    for task in tasks:
        edition = task["hackathon_edition"]
        task_num = task["task_number"]
        community_file = task.get("community_file", "")

        # Primary match: by community_file + task_number
        desc = None
        if community_file:
            key = (community_file, task_num)
            desc = all_descriptions.get(key)

        # Fallback: try all files for this edition (for tasks without community_file)
        if not desc:
            for filename in EDITION_FILES.get(edition, []):
                rel_path = f"hackathon/{filename}"
                key = (rel_path, task_num)
                if key in all_descriptions:
                    desc = all_descriptions[key]
                    break

        if desc:
            task["problem_statement_full"] = desc["problem_statement_full"]
            task["problem_statement_minimal"] = desc["problem_statement_minimal"]
            task["has_problem_statement"] = True
            matched += 1
        else:
            task["problem_statement_full"] = task.get("task_title", "")
            task["problem_statement_minimal"] = task.get("task_title", "")
            task["has_problem_statement"] = False
            unmatched += 1

        enriched_tasks.append(task)

    # Write enriched tasks
    output_path = os.path.join(DATASET_DIR, "tasks_6to9_enriched.jsonl")
    with open(output_path, "w") as f:
        for task in enriched_tasks:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")

    print(f"\nMatching results:", file=sys.stderr)
    print(f"  Matched: {matched}", file=sys.stderr)
    print(f"  Unmatched: {unmatched}", file=sys.stderr)
    print(f"\nWritten to: {output_path}", file=sys.stderr)

    # Also enrich instances file
    instances_path = os.path.join(DATASET_DIR, "instances_6to9_raw.jsonl")
    if os.path.exists(instances_path):
        with open(instances_path) as f:
            instances = [json.loads(line) for line in f]

        inst_matched = 0
        for inst in instances:
            edition = inst.get("hackathon_edition", "")
            task_num = inst.get("task_number", 0)
            community_file = inst.get("community_file", "")

            desc = None
            if community_file:
                key = (community_file, task_num)
                desc = all_descriptions.get(key)
            if not desc:
                for filename in EDITION_FILES.get(edition, []):
                    rel_path = f"hackathon/{filename}"
                    key = (rel_path, task_num)
                    if key in all_descriptions:
                        desc = all_descriptions[key]
                        break

            if desc:
                inst["problem_statement"] = desc["problem_statement_full"]
                inst["problem_statement_minimal"] = desc["problem_statement_minimal"]
                inst_matched += 1
            else:
                inst["problem_statement"] = inst.get("task_title", inst.get("pr_title", ""))
                inst["problem_statement_minimal"] = inst["problem_statement"]

        output_inst = os.path.join(DATASET_DIR, "instances_6to9.jsonl")
        with open(output_inst, "w") as f:
            for inst in instances:
                f.write(json.dumps(inst, ensure_ascii=False) + "\n")

        print(f"\nInstances enriched: {inst_matched}/{len(instances)}", file=sys.stderr)
        print(f"Written to: {output_inst}", file=sys.stderr)


if __name__ == "__main__":
    main()
