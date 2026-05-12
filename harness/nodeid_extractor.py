"""Nodeid extraction: collect-only delta as primary, diff parser as fallback."""

import re
import subprocess
from pathlib import Path

from .patch_utils import extract_added_lines, extract_test_files


def collect_nodeids(test_file: str, working_dir: str | Path, env: dict | None = None) -> tuple[set[str], str]:
    """Run pytest --collect-only to get all nodeids in a test file.

    Args:
        test_file: Relative path to the test file from working_dir
        working_dir: Directory to run pytest from (Paddle repo root)
        env: Optional environment variables (e.g., PYTHONPATH)

    Returns:
        (set_of_nodeids, error_message)
    """
    cmd = [
        "python", "-m", "pytest",
        "--collect-only", "-q",
        "--no-header",
        test_file,
    ]
    import os
    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=str(working_dir),
        env=run_env,
        timeout=120,
    )
    if result.returncode != 0 and not result.stdout.strip():
        return set(), result.stderr.strip()

    nodeids = set()
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        # pytest collect-only -q outputs lines like: path::Class::method
        if "::" in line and not line.startswith(("=", "-", "no tests", "ERROR")):
            nodeids.add(line)
    return nodeids, ""


def extract_delta_nodeids(
    test_files: list[str],
    working_dir: str | Path,
    test_patch: str,
    env: dict | None = None,
) -> tuple[list[str], list[str], str]:
    """Extract new/modified nodeids by comparing before/after test_patch.

    Primary path: uses pytest --collect-only delta.

    Args:
        test_files: List of test file paths (relative to working_dir)
        working_dir: Paddle repo root
        test_patch: The test patch content
        env: Optional environment for pytest

    Returns:
        (new_nodeids, baseline_nodeids_for_p2p, error_message)
        - new_nodeids: nodeids that appear after test_patch but not before (FAIL_TO_PASS candidates)
        - baseline_nodeids_for_p2p: selected existing nodeids for PASS_TO_PASS verification
    """
    from .patch_utils import apply_patch, revert_patch

    all_new = []
    all_baseline = []

    for test_file in test_files:
        # Check if file exists before patch (if not, it's entirely new)
        test_path = Path(working_dir) / test_file
        file_exists_before = test_path.exists()

        if not file_exists_before:
            # Entirely new test file — all its nodeids are FAIL_TO_PASS candidates
            # We need to apply the patch first to collect
            ok, err = apply_patch(working_dir, test_patch)
            if not ok:
                return [], [], f"Failed to apply test_patch: {err}"

            after_nodeids, collect_err = collect_nodeids(test_file, working_dir, env)
            revert_patch(working_dir, test_patch)

            if collect_err:
                return [], [], f"collect-only failed after patch: {collect_err}"

            all_new.extend(sorted(after_nodeids))
            # No baseline for new files — PASS_TO_PASS is empty (correct by design)
            continue

        # File exists — collect before-patch nodeids
        before_nodeids, err = collect_nodeids(test_file, working_dir, env)
        if err:
            return [], [], f"collect-only failed before patch on {test_file}: {err}"

        # Apply test_patch and collect after
        ok, apply_err = apply_patch(working_dir, test_patch)
        if not ok:
            return [], [], f"Failed to apply test_patch: {apply_err}"

        after_nodeids, err = collect_nodeids(test_file, working_dir, env)
        revert_patch(working_dir, test_patch)

        if err:
            return [], [], f"collect-only failed after patch on {test_file}: {err}"

        # Delta = new nodeids
        new_nodeids = after_nodeids - before_nodeids
        all_new.extend(sorted(new_nodeids))

        # Baseline for PASS_TO_PASS: select stable existing nodeids
        existing = sorted(before_nodeids & after_nodeids)
        # Take up to 5 baseline nodeids for PASS_TO_PASS verification
        baseline_count = min(5, len(existing))
        all_baseline.extend(existing[:baseline_count])

    return all_new, all_baseline, ""


def extract_nodeids_from_diff(test_patch: str, test_files: list[str]) -> list[str]:
    """Fallback: extract candidate nodeids by parsing diff added lines.

    Looks for new class definitions (class Test*) and new test methods (def test_*).
    Returns approximate nodeids — may not be perfectly accurate.
    """
    added_per_file = extract_added_lines(test_patch)
    candidates = []

    for test_file in test_files:
        matching_paths = [p for p in added_per_file if p == test_file or p.endswith(test_file)]
        for path in matching_paths:
            lines = added_per_file[path]
            current_class = None
            for line in lines:
                # Detect new class
                class_match = re.match(r"class (Test\w+)", line)
                if class_match:
                    current_class = class_match.group(1)

                # Detect new test method
                method_match = re.match(r"\s*def (test_\w+)", line)
                if method_match and current_class:
                    nodeid = f"{test_file}::{current_class}::{method_match.group(1)}"
                    candidates.append(nodeid)

    return candidates
