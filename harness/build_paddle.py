"""Source build management for Paddle (.cc/.cu samples only).

For .cc samples: full build → install wheel → verify import.
Fix state: apply code_patch → incremental build → reinstall wheel.
"""

import subprocess
from pathlib import Path

from .config import CMAKE_FLAGS
from .docker_env import exec_in_container


def full_build_in_container(
    container_id: str,
    paddle_dir: str = "/paddle",
    nproc: int | None = None,
) -> tuple[bool, str]:
    """Full source build of Paddle inside a Docker container.

    Steps:
        1. mkdir build && cd build
        2. cmake with configured flags
        3. make -j$(nproc)
        4. Install generated wheel
        5. Verify import

    Returns:
        (success, error_or_wheel_path)
    """
    # Construct cmake command
    cmake_args = " ".join(f"-D{k}={v}" for k, v in CMAKE_FLAGS.items())
    cmake_cmd = f"cd {paddle_dir} && mkdir -p build && cd build && cmake .. {cmake_args}"

    result = exec_in_container(container_id, ["bash", "-c", cmake_cmd], timeout=300)
    if result.returncode != 0:
        return False, f"cmake failed: {result.stderr[-500:]}"

    # Make
    jobs = nproc or "$(nproc)"
    make_cmd = f"cd {paddle_dir}/build && make -j{jobs}"
    result = exec_in_container(container_id, ["bash", "-c", make_cmd], timeout=7200)
    if result.returncode != 0:
        return False, f"make failed: {result.stderr[-500:]}"

    # Install wheel
    ok, err = install_local_wheel(container_id, paddle_dir)
    if not ok:
        return False, err

    return True, ""


def incremental_build_in_container(
    container_id: str,
    paddle_dir: str = "/paddle",
) -> tuple[bool, str]:
    """Incremental build after applying code_patch.

    Only recompiles changed files, then reinstalls wheel.
    """
    make_cmd = f"cd {paddle_dir}/build && make -j$(nproc)"
    result = exec_in_container(container_id, ["bash", "-c", make_cmd], timeout=3600)
    if result.returncode != 0:
        return False, f"incremental make failed: {result.stderr[-500:]}"

    ok, err = install_local_wheel(container_id, paddle_dir)
    if not ok:
        return False, err

    return True, ""


def install_local_wheel(
    container_id: str,
    paddle_dir: str = "/paddle",
) -> tuple[bool, str]:
    """Install the locally built Paddle wheel.

    Finds the generated .whl file and pip installs it with --force-reinstall.
    Then verifies import paddle works.
    """
    # Find the wheel
    find_cmd = f"find {paddle_dir}/python/dist -name 'paddlepaddle*.whl' -type f | sort -V | tail -1"
    result = exec_in_container(container_id, ["bash", "-c", find_cmd])
    wheel_path = result.stdout.strip()

    if not wheel_path:
        return False, "No wheel found in python/dist/"

    # Install
    install_cmd = f"pip install {wheel_path} --force-reinstall --no-deps"
    result = exec_in_container(container_id, ["bash", "-c", install_cmd], timeout=120)
    if result.returncode != 0:
        return False, f"pip install failed: {result.stderr[-300:]}"

    # Verify
    ok, err = verify_paddle_import(container_id)
    if not ok:
        return False, err

    return True, wheel_path


def verify_paddle_import(container_id: str) -> tuple[bool, str]:
    """Verify that paddle imports correctly after install."""
    verify_cmd = 'python -c "import paddle; print(paddle.__version__)"'
    result = exec_in_container(container_id, ["bash", "-c", verify_cmd], timeout=30)
    if result.returncode != 0:
        return False, f"import paddle failed: {result.stderr.strip()}"
    return True, result.stdout.strip()


def setup_python_overlay(
    container_id: str,
    paddle_dir: str = "/paddle",
) -> tuple[bool, str]:
    """Set up PYTHONPATH overlay for pure-Python samples.

    Puts the source tree's python/ at the front of PYTHONPATH so that
    modifications to .py files take effect without rebuilding.
    """
    # Verify the python/ directory exists
    check_cmd = f"test -d {paddle_dir}/python/paddle"
    result = exec_in_container(container_id, ["bash", "-c", check_cmd])
    if result.returncode != 0:
        return False, f"{paddle_dir}/python/paddle does not exist"

    return True, f"{paddle_dir}/python"


def checkout_commit(
    container_id: str,
    commit: str,
    paddle_dir: str = "/paddle",
) -> tuple[bool, str]:
    """Checkout a specific commit in the Paddle repo."""
    cmd = f"cd {paddle_dir} && git checkout {commit}"
    result = exec_in_container(container_id, ["bash", "-c", cmd], timeout=60)
    if result.returncode != 0:
        return False, f"git checkout failed: {result.stderr.strip()}"
    return True, ""
