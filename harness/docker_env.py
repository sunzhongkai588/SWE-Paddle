"""Docker container management for isolated pilot validation.

Docker is MANDATORY — no venv fallback. If Docker is unavailable, preflight fails.
"""

import subprocess
import json
from pathlib import Path

from .config import PADDLE_REPO_URL, HTTP_PROXY


def preflight_docker() -> tuple[bool, str]:
    """Check Docker availability. Returns (ok, error_message)."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return False, f"docker info failed: {result.stderr.strip()}"
        return True, ""
    except FileNotFoundError:
        return False, "docker command not found"
    except subprocess.TimeoutExpired:
        return False, "docker info timed out"


def get_image_digest(image: str) -> str:
    """Get the digest of a Docker image."""
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{index .RepoDigests 0}}", image],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return ""


def pull_image(image: str) -> tuple[bool, str]:
    """Pull a Docker image."""
    result = subprocess.run(
        ["docker", "pull", image],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, ""


def create_container(
    image: str,
    name: str,
    gpu: bool = True,
    volumes: dict[str, str] | None = None,
) -> tuple[str, str]:
    """Create a Docker container for a pilot sample.

    Args:
        image: Docker image to use
        name: Container name
        gpu: Whether to pass --gpus all
        volumes: Host:container volume mounts

    Returns:
        (container_id, error_message)
    """
    cmd = [
        "docker", "create",
        "--name", name,
        "-it",
        "--shm-size=32g",
    ]
    if gpu:
        cmd.extend(["--gpus", "all"])

    if volumes:
        for host_path, container_path in volumes.items():
            cmd.extend(["-v", f"{host_path}:{container_path}"])

    # Set proxy for network access
    cmd.extend(["-e", f"https_proxy={HTTP_PROXY}"])
    cmd.extend(["-e", f"http_proxy={HTTP_PROXY}"])

    cmd.append(image)
    cmd.append("/bin/bash")

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return "", result.stderr.strip()
    return result.stdout.strip(), ""


def start_container(container_id: str) -> tuple[bool, str]:
    """Start an existing container."""
    result = subprocess.run(
        ["docker", "start", container_id],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return False, result.stderr.strip()
    return True, ""


def exec_in_container(
    container_id: str,
    cmd: list[str],
    working_dir: str | None = None,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
    timeout: int = 3600,
) -> subprocess.CompletedProcess:
    """Execute a command inside a running container."""
    docker_cmd = ["docker", "exec"]
    if stdin is not None:
        docker_cmd.append("-i")
    if working_dir:
        docker_cmd.extend(["-w", working_dir])
    if env:
        for k, v in env.items():
            docker_cmd.extend(["-e", f"{k}={v}"])
    docker_cmd.append(container_id)
    docker_cmd.extend(cmd)

    return subprocess.run(
        docker_cmd,
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def remove_container(container_id: str, force: bool = True) -> None:
    """Remove a container."""
    cmd = ["docker", "rm"]
    if force:
        cmd.append("-f")
    cmd.append(container_id)
    subprocess.run(cmd, capture_output=True)


def container_name_for_sample(instance_id: str, phase: str) -> str:
    """Generate a deterministic container name for a sample."""
    safe_id = instance_id.replace("/", "-").replace("__", "-").lower()
    return f"paddleswe-{safe_id}-{phase}"


def select_dev_image(merged_at: str) -> str:
    """Select appropriate Paddle dev image based on merge date.

    Strategy: look up known stable images for each period.
    Must NOT use 'latest-*' rolling tags.
    """
    # Parse year-month from merged_at (e.g., "2024-05-23T06:49:15Z")
    year_month = merged_at[:7]  # "2024-05"

    # Known stable dev images by period
    # These should be verified against Paddle CI configs
    if year_month >= "2025-06":
        return "registry.baidubce.com/paddlepaddle/paddle_manylinux_devel:cuda12.3-cudnn9.0-trt8.6-gcc12.2"
    elif year_month >= "2024-09":
        return "registry.baidubce.com/paddlepaddle/paddle_manylinux_devel:cuda12.3-cudnn9.0-trt8.6-gcc12.2"
    elif year_month >= "2024-03":
        return "registry.baidubce.com/paddlepaddle/paddle_manylinux_devel:cuda12.0-cudnn8.9-trt8.6-gcc12.2"
    else:
        return "registry.baidubce.com/paddlepaddle/paddle_manylinux_devel:cuda11.8-cudnn8.6-trt8.5-gcc8.2"
