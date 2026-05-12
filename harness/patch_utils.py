"""Patch parsing, application, and file type classification."""

import re
import subprocess
from pathlib import Path

from .config import FileDiff, PatchInfo


def parse_diff(patch_str: str) -> PatchInfo:
    """Parse a unified diff string into structured PatchInfo."""
    info = PatchInfo()
    if not patch_str:
        return info

    # Split into per-file diffs
    file_diffs = re.split(r"^diff --git ", patch_str, flags=re.MULTILINE)
    for chunk in file_diffs:
        if not chunk.strip():
            continue
        # Extract file path from "a/path b/path"
        header_match = re.match(r"a/(.+?) b/(.+?)$", chunk, re.MULTILINE)
        if not header_match:
            continue
        path = header_match.group(2)
        info.files.append(FileDiff(path=path, hunks=chunk))

        # Classify file type
        if path.endswith(".cu"):
            info.has_cuda = True
        elif path.endswith((".cc", ".h", ".hpp", ".cpp")):
            info.has_cc = True
        elif path.endswith(".py"):
            info.has_python = True

    return info


def extract_test_files(patch_str: str) -> list[str]:
    """Extract pytest-targetable test files from a test_patch.

    Filters out non-.py files (e.g., CMakeLists.txt) and non-test paths.
    """
    info = parse_diff(patch_str)
    test_files = []
    for f in info.files:
        if not f.path.endswith(".py"):
            continue
        if "test" not in f.path:
            continue
        test_files.append(f.path)
    return test_files


def apply_patch(repo_dir: str | Path, patch_str: str, reverse: bool = False) -> tuple[bool, str]:
    """Apply a unified diff patch via git apply.

    Args:
        repo_dir: Path to the git repository
        patch_str: The unified diff content
        reverse: If True, apply in reverse (revert)

    Returns:
        (success, error_message)
    """
    cmd = ["git", "apply", "--whitespace=nowarn"]
    if reverse:
        cmd.append("-R")

    result = subprocess.run(
        cmd,
        input=patch_str,
        capture_output=True,
        text=True,
        cwd=str(repo_dir),
    )
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, ""


def revert_patch(repo_dir: str | Path, patch_str: str) -> tuple[bool, str]:
    """Revert a previously applied patch."""
    return apply_patch(repo_dir, patch_str, reverse=True)


def classify_code_patch(patch_str: str) -> str:
    """Classify the code_patch type for build strategy decisions.

    Returns: 'cuda', 'cc_only', or 'python_only'
    """
    info = parse_diff(patch_str)
    return info.code_patch_type


def get_modified_paths(patch_str: str) -> list[str]:
    """Extract all file paths modified by a patch."""
    info = parse_diff(patch_str)
    return [f.path for f in info.files]


def extract_added_lines(patch_str: str) -> dict[str, list[str]]:
    """Extract added lines (starting with +) per file from a diff.

    Returns: {file_path: [added_lines_without_plus_prefix]}
    """
    result: dict[str, list[str]] = {}
    info = parse_diff(patch_str)
    for f in info.files:
        added = []
        for line in f.hunks.split("\n"):
            if line.startswith("+") and not line.startswith("+++"):
                added.append(line[1:])
        if added:
            result[f.path] = added
    return result
