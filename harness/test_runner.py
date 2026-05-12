"""Pytest execution and result parsing."""

import os
import subprocess
from pathlib import Path

from .config import TEST_TIMEOUT_PER_NODEID, TEST_TIMEOUT_TOTAL, TestResult


def run_tests(
    test_nodeids: list[str],
    working_dir: str | Path,
    env: dict | None = None,
    timeout_per_nodeid: int = TEST_TIMEOUT_PER_NODEID,
    timeout_total: int = TEST_TIMEOUT_TOTAL,
) -> TestResult:
    """Execute pytest on specified nodeids and parse results.

    Args:
        test_nodeids: List of pytest nodeids to run
        working_dir: Directory to run from (Paddle repo root)
        env: Optional environment variables
        timeout_per_nodeid: Timeout per individual test (seconds)
        timeout_total: Total timeout for the entire run (seconds)

    Returns:
        TestResult with parsed pass/fail/error nodeids
    """
    if not test_nodeids:
        return TestResult(returncode=-1, stderr="No nodeids provided")

    cmd = [
        "python", "-m", "pytest",
        "-xvs" if len(test_nodeids) <= 5 else "-v",
        f"--timeout={timeout_per_nodeid}",
        "--tb=short",
        "--no-header",
        "-q",
        *test_nodeids,
    ]

    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(working_dir),
            env=run_env,
            timeout=timeout_total,
        )
    except subprocess.TimeoutExpired as e:
        return TestResult(
            timeout=True,
            returncode=-1,
            stdout=e.stdout or "",
            stderr=f"Total timeout ({timeout_total}s) exceeded",
        )

    return _parse_pytest_output(result.stdout, result.stderr, result.returncode)


def run_collect_only(
    test_files: list[str],
    working_dir: str | Path,
    env: dict | None = None,
) -> tuple[list[str], str]:
    """Run pytest --collect-only and return all collected nodeids.

    Returns:
        (list_of_nodeids, error_message)
    """
    cmd = [
        "python", "-m", "pytest",
        "--collect-only", "-q",
        "--no-header",
        *test_files,
    ]

    run_env = os.environ.copy()
    if env:
        run_env.update(env)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(working_dir),
            env=run_env,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return [], "collect-only timed out"

    if result.returncode != 0 and not result.stdout.strip():
        return [], result.stderr.strip()

    nodeids = []
    for line in result.stdout.strip().split("\n"):
        line = line.strip()
        if "::" in line and not line.startswith(("=", "-", "no tests", "ERROR")):
            nodeids.append(line)
    return nodeids, ""


def _parse_pytest_output(stdout: str, stderr: str, returncode: int) -> TestResult:
    """Parse pytest verbose output to extract per-nodeid results."""
    passed = []
    failed = []
    errors = []

    for line in stdout.split("\n"):
        line = line.strip()
        if not line:
            continue

        # pytest -v output: "nodeid PASSED", "nodeid FAILED", "nodeid ERROR"
        if " PASSED" in line:
            nodeid = line.split(" PASSED")[0].strip()
            if "::" in nodeid:
                passed.append(nodeid)
        elif " FAILED" in line:
            nodeid = line.split(" FAILED")[0].strip()
            if "::" in nodeid:
                failed.append(nodeid)
        elif " ERROR" in line:
            nodeid = line.split(" ERROR")[0].strip()
            if "::" in nodeid:
                errors.append(nodeid)

    # Also parse the FAILURES section for nodeids
    if "FAILED" in stdout:
        for match in _FAILED_PATTERN.finditer(stdout):
            nodeid = match.group(1)
            if nodeid not in failed:
                failed.append(nodeid)

    return TestResult(
        passed_nodeids=passed,
        failed_nodeids=failed,
        error_nodeids=errors,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


import re
_FAILED_PATTERN = re.compile(r"FAILED (.+?::.+?)(?:\s|$)")
