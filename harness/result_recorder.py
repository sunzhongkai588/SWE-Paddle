"""JSONL output recording, separating smoke vs verified results."""

import json
from dataclasses import asdict
from pathlib import Path

from .config import (
    DRYRUN_OUTPUT,
    PILOT_OUTPUT,
    SMOKE_OUTPUT,
    PilotResult,
    SmokeResult,
)


def write_smoke_results(results: list[SmokeResult], output_path: Path | None = None) -> Path:
    """Write smoke test results to JSONL."""
    path = output_path or SMOKE_OUTPUT
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    return path


def write_pilot_results(results: list[PilotResult], output_path: Path | None = None) -> Path:
    """Write verified pilot results to JSONL."""
    path = output_path or PILOT_OUTPUT
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    return path


def write_dryrun_result(result: PilotResult, output_path: Path | None = None) -> Path:
    """Write a single dry-run result to JSONL."""
    path = output_path or DRYRUN_OUTPUT
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
    return path


def load_pilot_results(path: Path) -> list[PilotResult]:
    """Load pilot results from a JSONL file."""
    results = []
    with open(path) as f:
        for line in f:
            data = json.loads(line)
            results.append(PilotResult(**data))
    return results
