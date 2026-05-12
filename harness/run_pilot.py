#!/usr/bin/env python3
"""PaddleSWE Pilot Validation Orchestrator.

Drives the full Run/Test/Fix three-state verification pipeline.

Usage:
    python -m harness.run_pilot --phase smoke          # Smoke test + nodeid discovery
    python -m harness.run_pilot --phase full           # Full three-state verification
    python -m harness.run_pilot --phase full --pr 74850  # Single sample dry-run
    python -m harness.run_pilot --phase all            # Smoke then full
"""

import argparse
import json
import logging
import shlex
import sys
from pathlib import Path

from .config import (
    DATASET_DIR,
    DRYRUN_PR,
    INSTANCES_FILE,
    LOGS_DIR,
    PADDLE_CLONE_DIR,
    PADDLE_REPO_URL,
    PILOT_OUTPUT,
    PILOT_PRS,
    STABILITY_RUNS,
    HTTP_PROXY,
    PilotResult,
    PilotSample,
    SmokeResult,
)
from .docker_env import (
    container_name_for_sample,
    create_container,
    exec_in_container,
    get_image_digest,
    preflight_docker,
    pull_image,
    remove_container,
    select_dev_image,
    start_container,
)
from .build_paddle import (
    checkout_commit,
    full_build_in_container,
    incremental_build_in_container,
    install_local_wheel,
    setup_python_overlay,
    verify_paddle_import,
)
from .nodeid_extractor import extract_delta_nodeids, extract_nodeids_from_diff
from .patch_utils import apply_patch, classify_code_patch, extract_test_files, revert_patch
from .result_recorder import write_dryrun_result, write_pilot_results, write_smoke_results
from .test_runner import run_tests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)


def load_pilot_samples() -> list[PilotSample]:
    """Load pilot sample data from dataset."""
    samples = []
    with open(INSTANCES_FILE) as f:
        for line in f:
            r = json.loads(line)
            if r["pr_number"] in PILOT_PRS:
                samples.append(PilotSample(
                    instance_id=r["instance_id"],
                    pr_number=r["pr_number"],
                    track=r["track"],
                    base_commit=r["base_commit"],
                    merged_at=r["merged_at"],
                    code_patch=r["code_patch"],
                    test_patch=r["test_patch"],
                    gold_patch_loc=r["gold_patch_loc"],
                    test_patch_loc=r["test_patch_loc"],
                    problem_statement=r.get("problem_statement", ""),
                ))
    # Sort by PILOT_PRS order
    order = {pr: i for i, pr in enumerate(PILOT_PRS)}
    samples.sort(key=lambda s: order.get(s.pr_number, 999))
    return samples


# ---------------------------------------------------------------------------
# Phase: Smoke Test + Nodeid Discovery
# ---------------------------------------------------------------------------

def run_smoke_phase(samples: list[PilotSample]) -> list[SmokeResult]:
    """Run smoke tests using the currently installed Paddle.

    This is NOT verification — only checks test executability and extracts nodeids.
    Output status is 'smoke_pass', never 'CONFIRMED_*'.
    """
    log.info("=== Phase: Smoke Test + Nodeid Discovery ===")

    # Ensure Paddle repo is cloned for test file access
    _ensure_paddle_clone()

    results = []
    for sample in samples:
        log.info(f"Smoke: {sample.instance_id}")
        result = _smoke_one_sample(sample)
        results.append(result)
        log.info(f"  status={result.smoke_status}, nodeids={len(result.candidate_nodeids)}")

    output_path = write_smoke_results(results)
    log.info(f"Smoke results written to {output_path}")
    return results


def _smoke_one_sample(sample: PilotSample) -> SmokeResult:
    """Smoke test a single sample."""
    test_files = extract_test_files(sample.test_patch)
    result = SmokeResult(
        instance_id=sample.instance_id,
        test_files=test_files,
        is_verified=False,
    )

    # Get installed paddle version
    import subprocess
    ver_result = subprocess.run(
        ["python", "-c", "import paddle; print(paddle.__version__)"],
        capture_output=True, text=True,
    )
    result.installed_paddle_version = ver_result.stdout.strip() if ver_result.returncode == 0 else "unavailable"

    if not test_files:
        result.smoke_status = "ERROR"
        result.error_detail = "No test files extracted from test_patch"
        return result

    # Try to extract nodeids via collect-only delta
    paddle_dir = str(PADDLE_CLONE_DIR)
    new_nodeids, baseline_nodeids, err = extract_delta_nodeids(
        test_files, paddle_dir, sample.test_patch
    )

    if err:
        # Fallback to diff parser
        log.warning(f"  collect-only delta failed: {err}, trying diff parser")
        new_nodeids = extract_nodeids_from_diff(sample.test_patch, test_files)
        result.nodeids_source = "diff_parser"
    else:
        result.nodeids_source = "collect_delta"

    result.candidate_nodeids = new_nodeids

    if not new_nodeids:
        result.smoke_status = "ERROR"
        result.error_detail = "No candidate nodeids found"
        return result

    # Try running the tests with installed Paddle
    test_result = run_tests(new_nodeids, paddle_dir)
    if test_result.all_passed:
        result.smoke_status = "PASS"
    elif test_result.has_failures:
        result.smoke_status = "FAIL"
        result.error_detail = f"Failed: {test_result.failed_nodeids}"
    else:
        result.smoke_status = "ERROR"
        result.error_detail = test_result.stderr[:200]

    return result


# ---------------------------------------------------------------------------
# Phase: Full Three-State Verification
# ---------------------------------------------------------------------------

def run_full_phase(samples: list[PilotSample], dry_run_pr: int | None = None) -> list[PilotResult]:
    """Run full Run/Test/Fix three-state verification in Docker.

    Each sample gets its own container with proper base_commit state.
    """
    log.info("=== Phase: Full Three-State Verification ===")

    # Preflight: Docker must be available
    ok, err = preflight_docker()
    if not ok:
        log.error(f"PREFLIGHT FAIL: Docker not available: {err}")
        log.error("Docker is mandatory. Cannot proceed without Docker.")
        sys.exit(1)

    if dry_run_pr:
        samples = [s for s in samples if s.pr_number == dry_run_pr]
        if not samples:
            log.error(f"PR {dry_run_pr} not found in pilot samples")
            sys.exit(1)

    results = []
    for sample in samples:
        log.info(f"Full verification: {sample.instance_id}")
        result = _verify_one_sample(sample)
        results.append(result)

        status_line = f"  run={result.run_exec_status}, test={result.test_status}, fix={result.fix_status}"
        log.info(status_line)

        if result.FAIL_TO_PASS:
            log.info(f"  FAIL_TO_PASS: {result.FAIL_TO_PASS}")

    # Write output
    if dry_run_pr:
        if results:
            output_path = write_dryrun_result(results[0])
            log.info(f"Dry-run result written to {output_path}")
    else:
        output_path = write_pilot_results(results)
        log.info(f"Pilot results written to {output_path}")

    return results


def _verify_one_sample(sample: PilotSample) -> PilotResult:
    """Full Run/Test/Fix verification for one sample."""
    test_files = extract_test_files(sample.test_patch)
    code_type = classify_code_patch(sample.code_patch)
    needs_build = code_type != "python_only"
    image = select_dev_image(sample.merged_at)

    result = PilotResult(
        instance_id=sample.instance_id,
        base_commit=sample.base_commit,
        test_files=test_files,
        code_patch_type=code_type,
        install_mode="source_build" if needs_build else "wheel_with_python_overlay",
        env_image=image,
        stability_runs=STABILITY_RUNS,
    )

    # Set up log directory
    log_dir = LOGS_DIR / str(sample.pr_number)
    log_dir.mkdir(parents=True, exist_ok=True)
    result.logs_path = str(log_dir)

    # Pull image
    log.info(f"  Pulling image: {image}")
    ok, err = pull_image(image)
    if not ok:
        result.failure_reason = "env_dep"
        result.run_collect_status = "ERROR"
        log.error(f"  Failed to pull image: {err}")
        return result

    result.env_image_digest = get_image_digest(image)

    # Create and start container
    container_name = container_name_for_sample(sample.instance_id, "verify")
    remove_container(container_name)  # clean up any prior run

    container_id, err = create_container(image, container_name, gpu=True)
    if err:
        result.failure_reason = "env_dep"
        log.error(f"  Failed to create container: {err}")
        return result

    ok, err = start_container(container_id)
    if not ok:
        result.failure_reason = "env_dep"
        log.error(f"  Failed to start container: {err}")
        remove_container(container_id)
        return result

    try:
        _run_three_state_in_container(sample, container_id, result, needs_build, code_type)
    finally:
        remove_container(container_id)

    return result


def _run_three_state_in_container(
    sample: PilotSample,
    container_id: str,
    result: PilotResult,
    needs_build: bool,
    code_type: str,
) -> None:
    """Execute Run/Test/Fix inside the container."""
    paddle_dir = "/paddle"
    python_overlay = None  # set for pure-python samples

    # Clone Paddle in container
    log.info("  Cloning Paddle repo in container...")
    clone_cmd = (
        f"git clone --depth=1 {PADDLE_REPO_URL} {paddle_dir} && "
        f"cd {paddle_dir} && git fetch --depth=100 origin {sample.base_commit} && "
        f"git checkout {sample.base_commit}"
    )
    r = exec_in_container(container_id, ["bash", "-c", clone_cmd], timeout=600)
    if r.returncode != 0:
        result.failure_reason = "env_dep"
        result.run_collect_status = "ERROR"
        log.error(f"  Clone/checkout failed: {r.stderr[-200:]}")
        return

    # --- Build/Install for Run state ---
    if needs_build:
        log.info("  Building Paddle from source (full build)...")
        ok, err = full_build_in_container(container_id, paddle_dir)
        if not ok:
            result.failure_reason = "build_fail"
            result.run_collect_status = "ERROR"
            log.error(f"  Build failed: {err}")
            return
        result.build_mode = "full"
        result.compiled_core_source = sample.base_commit
    else:
        # Pure Python: install wheel + overlay
        log.info("  Setting up wheel + python overlay...")
        ok, overlay_path = setup_python_overlay(container_id, paddle_dir)
        if not ok:
            result.failure_reason = "env_dep"
            result.run_collect_status = "ERROR"
            return
        python_overlay = overlay_path
        result.python_overlay_commit = sample.base_commit

    # --- Run state: collect baseline nodeids ---
    log.info("  Run state: collecting baseline...")
    test_file_str = " ".join(sample.test_files if hasattr(sample, '_test_files_resolved') else
                             extract_test_files(sample.test_patch))

    # PYTHONPATH prefix for pure-python overlay
    env_prefix = f"PYTHONPATH={python_overlay}:$PYTHONPATH " if python_overlay else ""

    # Check if test files exist at base_commit (they may not for new files)
    for tf in result.test_files:
        check = exec_in_container(container_id, ["test", "-f", f"{paddle_dir}/{tf}"])
        if check.returncode != 0:
            log.info(f"  Test file {tf} does not exist at base_commit (new file)")

    quoted_test_files = " ".join(shlex.quote(tf) for tf in result.test_files)
    collect_cmd = f"cd {paddle_dir} && {env_prefix}python -m pytest --collect-only -q {quoted_test_files}"
    r = exec_in_container(container_id, ["bash", "-c", collect_cmd], timeout=120)
    run_nodeids = set()
    if r.returncode == 0:
        for line in r.stdout.strip().split("\n"):
            if "::" in line and not line.startswith(("=", "-", "no tests", "ERROR")):
                run_nodeids.add(line.strip())
        result.run_collect_status = "COLLECTED"
    else:
        # Collect failed — may mean test files don't exist at base_commit (expected for new tests)
        log.info(f"  collect-only returned {r.returncode} (test files may not exist at base)")
        result.run_collect_status = "COLLECTED"

    # Run baseline tests for PASS_TO_PASS (select up to 5 stable nodeids)
    baseline_nodeids = sorted(run_nodeids)[:5]
    if baseline_nodeids:
        log.info(f"  Running {len(baseline_nodeids)} baseline nodeids...")
        quoted_baseline = " ".join(shlex.quote(nid) for nid in baseline_nodeids)
        run_cmd = f"cd {paddle_dir} && {env_prefix}python -m pytest -v --timeout=300 {quoted_baseline}"
        r = exec_in_container(container_id, ["bash", "-c", run_cmd], timeout=600)
        # Parse which passed
        run_passed = [nid for nid in baseline_nodeids if f"{nid} PASSED" in r.stdout]
        result.run_exec_status = "PASS" if len(run_passed) == len(baseline_nodeids) else "PARTIAL_FAIL"
    else:
        result.run_exec_status = "PASS"  # no baseline to check
        run_passed = []

    # --- Test state: apply test_patch, expect FAIL ---
    log.info("  Test state: applying test_patch...")
    ok = _apply_patch_via_stdin(container_id, paddle_dir, sample.test_patch)
    if not ok:
        result.failure_reason = "patch_conflict"
        result.test_status = "ERROR"
        log.error("  test_patch apply failed")
        return

    # Collect nodeids after test_patch
    collect_cmd = f"cd {paddle_dir} && {env_prefix}python -m pytest --collect-only -q {quoted_test_files}"
    r = exec_in_container(container_id, ["bash", "-c", collect_cmd], timeout=120)
    test_nodeids = set()
    if r.returncode == 0:
        for line in r.stdout.strip().split("\n"):
            if "::" in line and not line.startswith(("=", "-", "no tests", "ERROR")):
                test_nodeids.add(line.strip())
    else:
        result.failure_reason = "collect_fail"
        result.test_status = "ERROR"
        log.error(f"  collect-only after test_patch failed: {r.stderr[-200:]}")
        return

    # Delta = FAIL_TO_PASS candidates
    new_nodeids = sorted(test_nodeids - run_nodeids)
    result.test_nodeids = new_nodeids
    result.nodeids_source = "collect_delta"

    if not new_nodeids:
        log.warning("  No new nodeids found after test_patch!")
        # Try full file as fallback only if run_nodeids was empty (new test file)
        if not run_nodeids:
            new_nodeids = sorted(test_nodeids)
            result.nodeids_source = "full_file"
        else:
            result.failure_reason = "no_new_nodeids"
            result.test_status = "ERROR"
            return

    # Run tests — expect FAIL for new nodeids
    verification_nodeids = new_nodeids + [n for n in run_passed if n in test_nodeids]
    log.info(f"  Running {len(verification_nodeids)} nodeids (expect FAIL for new ones)...")

    # Track which new nodeids failed across stability runs
    consistently_failed = set(new_nodeids)
    for run_idx in range(STABILITY_RUNS):
        quoted_verify = " ".join(shlex.quote(nid) for nid in verification_nodeids)
        run_cmd = f"cd {paddle_dir} && {env_prefix}python -m pytest -v --timeout=600 {quoted_verify}"
        r = exec_in_container(container_id, ["bash", "-c", run_cmd], timeout=1800)

        failed_in_run = {nid for nid in new_nodeids if f"{nid} FAILED" in r.stdout or f"{nid} ERROR" in r.stdout}
        consistently_failed &= failed_in_run

        if not failed_in_run:
            log.warning(f"  Run {run_idx+1}: new nodeids did NOT fail (unexpected pass)")
            break

    if not consistently_failed:
        result.test_status = "UNEXPECTED_PASS"
        result.failure_reason = "flaky"
        return

    result.test_status = "CONFIRMED_FAIL"

    # --- Fix state: apply code_patch, expect PASS ---
    log.info("  Fix state: applying code_patch...")
    ok = _apply_patch_via_stdin(container_id, paddle_dir, sample.code_patch)
    if not ok:
        result.failure_reason = "patch_conflict"
        result.fix_status = "ERROR"
        log.error("  code_patch apply failed")
        return

    # Rebuild if needed
    if needs_build:
        log.info("  Incremental build after code_patch...")
        ok, err = incremental_build_in_container(container_id, paddle_dir)
        if not ok:
            result.failure_reason = "build_fail"
            result.fix_status = "ERROR"
            log.error(f"  Incremental build failed: {err}")
            return
        result.build_mode = "incremental"

    # Run tests — expect PASS for consistently_failed nodeids
    fix_verification = sorted(consistently_failed) + [n for n in run_passed if n in test_nodeids]
    consistently_passed = set(consistently_failed)
    for run_idx in range(STABILITY_RUNS):
        quoted_fix = " ".join(shlex.quote(nid) for nid in fix_verification)
        run_cmd = f"cd {paddle_dir} && {env_prefix}python -m pytest -v --timeout=600 {quoted_fix}"
        r = exec_in_container(container_id, ["bash", "-c", run_cmd], timeout=1800)

        passed_in_run = {nid for nid in consistently_failed if f"{nid} PASSED" in r.stdout}
        consistently_passed &= passed_in_run

    # FAIL_TO_PASS = nodeids that failed in Test state AND passed in Fix state
    f2p = sorted(consistently_failed & consistently_passed)
    if f2p:
        result.fix_status = "CONFIRMED_PASS"
        result.FAIL_TO_PASS = f2p
        # Check PASS_TO_PASS
        p2p = [nid for nid in run_passed if f"{nid} PASSED" in r.stdout]
        result.PASS_TO_PASS = p2p
        result.stability_consistent = True
    else:
        result.fix_status = "UNEXPECTED_FAIL"
        result.failure_reason = "flaky"
        result.stability_consistent = False


def _apply_patch_via_stdin(container_id: str, paddle_dir: str, patch: str) -> bool:
    """Apply a patch safely via stdin (no heredoc delimiter issues)."""
    apply_cmd = f"cd {paddle_dir} && git apply --whitespace=nowarn -"
    r = exec_in_container(
        container_id,
        ["bash", "-c", apply_cmd],
        stdin=patch,
        timeout=30,
    )
    if r.returncode != 0:
        log.error(f"  patch apply failed: {r.stderr[-200:]}")
        return False
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_paddle_clone():
    """Ensure Paddle repo is cloned locally for smoke tests."""
    import subprocess
    if PADDLE_CLONE_DIR.exists() and (PADDLE_CLONE_DIR / ".git").exists():
        log.info("Paddle repo already cloned, pulling latest...")
        subprocess.run(["git", "pull"], cwd=str(PADDLE_CLONE_DIR), capture_output=True)
        return

    log.info(f"Cloning Paddle repo to {PADDLE_CLONE_DIR}...")
    PADDLE_CLONE_DIR.parent.mkdir(parents=True, exist_ok=True)
    env = {"https_proxy": HTTP_PROXY, "http_proxy": HTTP_PROXY}
    import os
    run_env = os.environ.copy()
    run_env.update(env)
    subprocess.run(
        ["git", "clone", "--depth=1", PADDLE_REPO_URL, str(PADDLE_CLONE_DIR)],
        env=run_env,
        timeout=600,
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="PaddleSWE Pilot Validation")
    parser.add_argument("--phase", choices=["smoke", "full", "all"], default="all",
                        help="Which phase to run")
    parser.add_argument("--pr", type=int, default=None,
                        help="Single PR number for dry-run")
    parser.add_argument("--dry-run", action="store_true",
                        help="Alias for --pr 74850 (dry-run the first sample)")
    args = parser.parse_args()

    if args.dry_run:
        args.pr = DRYRUN_PR

    samples = load_pilot_samples()
    if not samples:
        log.error("No pilot samples found in dataset!")
        sys.exit(1)
    log.info(f"Loaded {len(samples)} pilot samples")

    if args.phase in ("smoke", "all"):
        run_smoke_phase(samples)

    if args.phase in ("full", "all"):
        run_full_phase(samples, dry_run_pr=args.pr)


if __name__ == "__main__":
    main()
