#!/usr/bin/env python3
"""Direct F2P/P2P verification for pure-Python samples (no Docker needed).

Strategy: Selective file revert
- Installed Paddle 3.3.1 already has all fixes (Fix state baseline)
- Test state: revert ONLY the files modified by code_patch to base_commit versions
- Fix state: restore installed Paddle's files (already correct)
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parent.parent
PADDLE_CLONE = PROJ_ROOT / "harness" / "Paddle"
DATASET = PROJ_ROOT / "dataset" / "instances_6to9.jsonl"
OUTPUT = PROJ_ROOT / "dataset" / "pilot_python_verified.jsonl"
PROXY = "http://agent.baidu.com:8891"
STABILITY_RUNS = 3
PYTHON_PILOT_PRS = [63302, 64519, 63728]

# Installed paddle location
SITE_PACKAGES = Path("/usr/local/lib/python3.10/dist-packages")
INSTALLED_PADDLE = SITE_PACKAGES / "paddle"


def run_cmd(cmd, cwd=None, timeout=120, env=None):
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout, env=run_env)
        return r.returncode, r.stdout, r.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "TIMEOUT"


def fetch_commit(commit):
    env = {"https_proxy": PROXY, "http_proxy": PROXY}
    rc, _, err = run_cmd(
        ["git", "fetch", "--depth=1", "origin", commit],
        cwd=str(PADDLE_CLONE), timeout=180, env=env
    )
    return rc == 0


def get_code_patch_files(code_patch):
    """Extract Python file paths from code_patch."""
    files = []
    for match in re.finditer(r"^diff --git a/(.+?) b/(.+?)$", code_patch, re.MULTILINE):
        path = match.group(2)
        if path.endswith(".py") and path.startswith("python/"):
            files.append(path)
    return files


def map_to_installed(repo_path):
    """Map a repo path like python/paddle/nn/loss.py to installed location."""
    # repo: python/paddle/nn/layer/loss.py → installed: /usr/.../paddle/nn/layer/loss.py
    if repo_path.startswith("python/"):
        rel = repo_path[len("python/"):]  # paddle/nn/layer/loss.py
        return INSTALLED_PADDLE.parent / rel
    return None


def revert_files_to_base(code_patch_files, base_commit):
    """Replace installed files with base_commit versions. Returns backup info."""
    backups = {}
    for repo_path in code_patch_files:
        installed_path = map_to_installed(repo_path)
        if installed_path is None or not installed_path.exists():
            continue

        # Backup current (fixed) version
        backup_path = installed_path.with_suffix(installed_path.suffix + ".bak_paddleswe")
        shutil.copy2(str(installed_path), str(backup_path))
        backups[str(installed_path)] = str(backup_path)

        # Get base_commit version
        rc, content, err = run_cmd(
            ["git", "show", f"{base_commit}:{repo_path}"],
            cwd=str(PADDLE_CLONE), timeout=30
        )
        if rc == 0:
            installed_path.write_text(content)
        else:
            # File might not exist at base_commit (new file added by PR)
            # Remove it to simulate "not yet added"
            installed_path.unlink()

    return backups


def restore_files(backups):
    """Restore backed up files."""
    for installed_path, backup_path in backups.items():
        installed_path = Path(installed_path)
        backup_path = Path(backup_path)
        if backup_path.exists():
            shutil.copy2(str(backup_path), str(installed_path))
            backup_path.unlink()
        elif not installed_path.exists():
            # Was deleted (new file), backup should restore it
            pass


def write_test_file(test_dir, test_patch):
    """Extract and write test files from test_patch (for new files)."""
    files_written = []
    chunks = re.split(r"^diff --git ", test_patch, flags=re.MULTILINE)
    for chunk in chunks:
        if not chunk.strip():
            continue
        header = re.match(r"a/(.+?) b/(.+?)$", chunk, re.MULTILINE)
        if not header:
            continue
        path = header.group(2)
        if not path.endswith(".py") or "test" not in path:
            continue

        # Reconstruct file content from diff
        lines = []
        in_hunk = False
        for line in chunk.split("\n"):
            if line.startswith("@@"):
                in_hunk = True
                continue
            if in_hunk:
                if line.startswith("+"):
                    lines.append(line[1:])
                elif line.startswith(" "):
                    lines.append(line[1:])
                elif line.startswith("-"):
                    pass
                elif line.startswith("\\"):
                    pass
                else:
                    lines.append(line)

        target = test_dir / Path(path).name
        target.write_text("\n".join(lines))
        files_written.append(str(target))
    return files_written


def run_pytest(test_files, timeout=300):
    """Run pytest on test files using the installed Paddle."""
    cmd = ["python3", "-m", "pytest", "-v", "--tb=short", "--no-header", f"--timeout={timeout}"]
    cmd.extend(test_files)

    rc, stdout, stderr = run_cmd(cmd, timeout=timeout + 30)

    passed = []
    failed = []
    for line in stdout.split("\n"):
        if " PASSED" in line and "::" in line:
            passed.append(line.split(" PASSED")[0].strip())
        elif " FAILED" in line and "::" in line:
            failed.append(line.split(" FAILED")[0].strip())
        elif " ERROR" in line and "::" in line:
            failed.append(line.split(" ERROR")[0].strip())

    return {"rc": rc, "passed": passed, "failed": failed, "stdout": stdout, "stderr": stderr}


def verify_sample(pr_number, instance):
    print(f"\n{'='*60}")
    print(f"PR {pr_number}: {instance['instance_id']}")
    print(f"{'='*60}")

    base_commit = instance["base_commit"]
    test_patch = instance["test_patch"]
    code_patch = instance["code_patch"]

    result = {
        "instance_id": instance["instance_id"],
        "base_commit": base_commit,
        "test_files": [],
        "test_nodeids": [],
        "FAIL_TO_PASS": [],
        "PASS_TO_PASS": [],
        "run_collect_status": "",
        "run_exec_status": "PASS",
        "test_status": "",
        "fix_status": "",
        "install_mode": "selective_file_revert",
        "build_mode": "none",
        "code_patch_type": "python_only",
        "nodeids_source": "full_file",
        "stability_runs": STABILITY_RUNS,
        "stability_consistent": False,
        "failure_reason": "",
    }

    # Identify files to revert
    code_files = get_code_patch_files(code_patch)
    print(f"  Code patch files: {code_files}")

    # Fetch base_commit
    print(f"  Fetching {base_commit[:12]}...")
    if not fetch_commit(base_commit):
        result["failure_reason"] = "env_dep"
        result["run_collect_status"] = "ERROR"
        return result

    result["run_collect_status"] = "COLLECTED"

    # Write test files to temp dir
    test_dir = Path(tempfile.mkdtemp(prefix=f"paddleswe_test_{pr_number}_"))
    test_files = write_test_file(test_dir, test_patch)
    result["test_files"] = test_files
    print(f"  Test files: {[Path(f).name for f in test_files]}")

    if not test_files:
        result["failure_reason"] = "patch_conflict"
        result["test_status"] = "ERROR"
        return result

    # --- STAGE: Fix first (sanity check - tests should PASS with current Paddle) ---
    print(f"\n  [Fix state] Running tests with installed Paddle (expect PASS)...")
    fix_results = []
    for run_i in range(STABILITY_RUNS):
        r = run_pytest(test_files, timeout=300)
        fix_results.append(r)
        status = "PASS" if r["rc"] == 0 and not r["failed"] else "FAIL"
        print(f"    Run {run_i+1}: {status} ({len(r['passed'])} passed, {len(r['failed'])} failed)")
        if status == "FAIL" and r["stdout"]:
            for line in r["stdout"].split("\n")[-20:]:
                if "FAILED" in line or "Error" in line or "assert" in line.lower():
                    print(f"      {line[:100]}")

    fix_all_pass = all(r["rc"] == 0 and not r["failed"] for r in fix_results)
    if fix_all_pass:
        result["fix_status"] = "CONFIRMED_PASS"
        result["FAIL_TO_PASS"] = fix_results[0]["passed"]
        result["test_nodeids"] = fix_results[0]["passed"]
        print(f"  ✓ Fix state: CONFIRMED_PASS ({len(fix_results[0]['passed'])} nodeids)")
    else:
        result["fix_status"] = "UNEXPECTED_FAIL"
        result["failure_reason"] = "flaky"
        print(f"  ✗ Fix state: tests failed even with installed Paddle!")
        shutil.rmtree(test_dir, ignore_errors=True)
        return result

    # --- STAGE: Test (revert code_patch files, tests should FAIL) ---
    print(f"\n  [Test state] Reverting {len(code_files)} files to base_commit...")
    backups = revert_files_to_base(code_files, base_commit)
    print(f"    Reverted: {list(backups.keys())}")

    try:
        test_results = []
        for run_i in range(STABILITY_RUNS):
            r = run_pytest(test_files, timeout=300)
            test_results.append(r)
            has_failure = r["rc"] != 0 or r["failed"]
            status = "FAIL" if has_failure else "PASS"
            print(f"    Run {run_i+1}: {status} (rc={r['rc']}, {len(r['failed'])} failed)")
            if "ImportError" in r["stdout"] or "AttributeError" in r["stdout"]:
                print(f"      → Import/Attribute error (API removed from base_commit)")

        test_all_fail = all(r["rc"] != 0 or r["failed"] for r in test_results)
        if test_all_fail:
            result["test_status"] = "CONFIRMED_FAIL"
            print(f"  ✓ Test state: CONFIRMED_FAIL (3/3 consistent)")
            result["stability_consistent"] = True
        else:
            result["test_status"] = "UNEXPECTED_PASS"
            result["failure_reason"] = "flaky"
            result["stability_consistent"] = False
            print(f"  ✗ Test state: some runs passed unexpectedly")
    finally:
        # ALWAYS restore files
        print(f"\n  Restoring installed Paddle files...")
        restore_files(backups)
        print(f"  ✓ Files restored")

    # Cleanup
    shutil.rmtree(test_dir, ignore_errors=True)

    # Final summary for this sample
    if result["test_status"] == "CONFIRMED_FAIL" and result["fix_status"] == "CONFIRMED_PASS":
        print(f"\n  ★ VERIFIED: FAIL_TO_PASS = {len(result['FAIL_TO_PASS'])} nodeids")

    return result


def main():
    samples = {}
    with open(DATASET) as f:
        for line in f:
            r = json.loads(line)
            if r["pr_number"] in PYTHON_PILOT_PRS:
                samples[r["pr_number"]] = r

    print(f"Loaded {len(samples)} pure-Python pilot samples")
    print(f"Strategy: Selective file revert (revert code_patch files to base_commit)")
    print(f"Installed Paddle: {INSTALLED_PADDLE}")

    # Verify installed Paddle works
    rc, ver, _ = run_cmd(["python3", "-c", "import paddle; print(paddle.__version__)"])
    print(f"Paddle version: {ver.strip()}")

    results = []
    for pr in PYTHON_PILOT_PRS:
        if pr in samples:
            result = verify_sample(pr, samples[pr])
            results.append(result)

    # Write output
    with open(OUTPUT, "w") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\n{'='*60}")
    print(f"FINAL SUMMARY")
    print(f"{'='*60}")
    verified = [r for r in results if r["fix_status"] == "CONFIRMED_PASS" and r["test_status"] == "CONFIRMED_FAIL"]
    print(f"Fully verified (F2P extracted): {len(verified)}/{len(results)}")
    for r in results:
        ok = r["fix_status"] == "CONFIRMED_PASS" and r["test_status"] == "CONFIRMED_FAIL"
        status = "✓" if ok else "✗"
        f2p = len(r["FAIL_TO_PASS"])
        print(f"  {status} {r['instance_id']}: test={r['test_status']}, fix={r['fix_status']}, F2P={f2p}")
    print(f"\nOutput: {OUTPUT}")


if __name__ == "__main__":
    main()
