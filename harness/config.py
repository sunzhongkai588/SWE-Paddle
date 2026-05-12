"""PaddleSWE harness configuration and data structures."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Derive all paths from repo root (never hardcode absolute paths)
REPO_ROOT = Path(__file__).resolve().parent.parent
HARNESS_DIR = REPO_ROOT / "harness"
DATASET_DIR = REPO_ROOT / "dataset"
LOGS_DIR = HARNESS_DIR / "logs"

PADDLE_CLONE_DIR = HARNESS_DIR / "Paddle"
PADDLE_REPO_URL = "https://github.com/PaddlePaddle/Paddle.git"

# Dataset files
TRACK_A_FILE = DATASET_DIR / "track_a_bugfix.jsonl"
TRACK_C_FILE = DATASET_DIR / "track_c_feature.jsonl"
INSTANCES_FILE = DATASET_DIR / "instances.jsonl"

# Output files
SMOKE_OUTPUT = DATASET_DIR / "pilot_smoke_nodeids.jsonl"
DRYRUN_OUTPUT = DATASET_DIR / "pilot_dryrun_74850.jsonl"
PILOT_OUTPUT = DATASET_DIR / "mixed_pilot_verified_5.jsonl"

# Pilot sample PR numbers (mixed Track A/C)
PILOT_PRS = [74850, 74851, 63302, 64519, 63728]
DRYRUN_PR = 74850

# Build configuration
CMAKE_FLAGS = {
    "PY_VERSION": "3.10",
    "WITH_GPU": "ON",
    "WITH_TESTING": "ON",
    "CMAKE_BUILD_TYPE": "Release",
    "WITH_DISTRIBUTE": "OFF",
}

# Test execution
TEST_TIMEOUT_PER_NODEID = 600  # seconds
TEST_TIMEOUT_TOTAL = 1800  # seconds per sample
STABILITY_RUNS = 3

# Proxy (for network access within Baidu)
HTTP_PROXY = "http://agent.baidu.com:8891"


@dataclass
class FileDiff:
    """A single file's diff from a unified patch."""

    path: str
    hunks: str  # raw hunk text


@dataclass
class PatchInfo:
    """Parsed patch metadata."""

    files: list[FileDiff] = field(default_factory=list)
    has_cuda: bool = False  # .cu files
    has_cc: bool = False  # .cc/.h files
    has_python: bool = False  # .py files
    test_files: list[str] = field(default_factory=list)  # pytest-targetable files

    @property
    def needs_source_build(self) -> bool:
        return self.has_cuda or self.has_cc

    @property
    def code_patch_type(self) -> str:
        if self.has_cuda:
            return "cuda"
        if self.has_cc:
            return "cc_only"
        return "python_only"


@dataclass
class PilotSample:
    """A single pilot instance loaded from dataset."""

    instance_id: str
    pr_number: int
    track: str
    base_commit: str
    merged_at: str
    code_patch: str
    test_patch: str
    gold_patch_loc: int
    test_patch_loc: int
    problem_statement: str = ""


@dataclass
class TestResult:
    """Result of a single pytest run."""

    passed_nodeids: list[str] = field(default_factory=list)
    failed_nodeids: list[str] = field(default_factory=list)
    error_nodeids: list[str] = field(default_factory=list)
    timeout: bool = False
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""

    @property
    def all_passed(self) -> bool:
        return len(self.failed_nodeids) == 0 and len(self.error_nodeids) == 0

    @property
    def has_failures(self) -> bool:
        return len(self.failed_nodeids) > 0 or len(self.error_nodeids) > 0


@dataclass
class PilotResult:
    """Final verified result for one pilot sample."""

    instance_id: str
    base_commit: str
    test_files: list[str] = field(default_factory=list)
    test_nodeids: list[str] = field(default_factory=list)
    FAIL_TO_PASS: list[str] = field(default_factory=list)
    PASS_TO_PASS: list[str] = field(default_factory=list)

    # Three-state verification status
    run_collect_status: str = ""  # COLLECTED / ERROR
    run_exec_status: str = ""  # PASS / PARTIAL_FAIL / ERROR
    test_status: str = ""  # CONFIRMED_FAIL / UNEXPECTED_PASS / ERROR
    fix_status: str = ""  # CONFIRMED_PASS / UNEXPECTED_FAIL / ERROR

    # Build/install info
    install_mode: str = ""  # source_build / wheel_with_python_overlay
    build_mode: str = ""  # full / incremental
    code_patch_type: str = ""  # cuda / cc_only / python_only

    # Environment provenance
    env_image: str = ""
    env_image_digest: str = ""
    wheel_version: Optional[str] = None
    wheel_source: Optional[str] = None
    python_overlay_commit: Optional[str] = None
    compiled_core_source: Optional[str] = None

    # Nodeid extraction
    nodeids_source: str = ""  # collect_delta / diff_parser / full_file

    # Stability
    stability_runs: int = STABILITY_RUNS
    stability_consistent: bool = False

    # Logs
    logs_path: str = ""

    # Failure info (if not verified)
    failure_reason: str = ""  # build_fail / patch_conflict / import_error / timeout / flaky / env_dep / wheel_incompat


@dataclass
class SmokeResult:
    """Smoke test result (non-verification)."""

    instance_id: str
    test_files: list[str] = field(default_factory=list)
    candidate_nodeids: list[str] = field(default_factory=list)
    smoke_status: str = ""  # PASS / FAIL / ERROR
    installed_paddle_version: str = ""
    nodeids_source: str = ""
    is_verified: bool = False  # always False for smoke
    error_detail: str = ""
