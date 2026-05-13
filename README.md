# PaddleSWE-Bench

A SWE-bench style Coding Agent Benchmark built from PaddlePaddle Hackathon (6th~9th) tasks.

## What is this?

PaddleSWE-Bench evaluates coding agents on real-world PaddlePaddle framework tasks — bug fixes involving CUDA kernels and new API implementations. Each task comes from a merged PR with structured problem descriptions from the hackathon community.

**Unique properties:**
- Only SWE-bench variant covering CUDA kernel code
- Minimal data contamination risk (Chinese + niche training data)
- Structured task descriptions (not raw GitHub issues)
- Task-type-aware evaluation (Bug Fix vs Feature Impl)

## Dataset

| File | Count | Description |
|------|-------|-------------|
| `dataset/instances.jsonl` | 89 | Authoritative dataset (manually reviewed) |
| `dataset/track_a_bugfix.jsonl` | 10 | Track A: Bug Fix (0-Size, precision, kernel fixes) |
| `dataset/track_c_feature.jsonl` | 58 | Track C: Feature Implementation (new APIs + enhancements) |
| `dataset/excluded.jsonl` | 21 | Excluded (migrations, trivial patches) |

## Evaluation Design

| Track | Input | Goal | Metric |
|-------|-------|------|--------|
| **A: Bug Fix** | base_commit + test_patch (failing) + problem_statement | Generate code_patch to make tests pass | Pass@1 (F2P + P2P) |
| **C: Feature Impl** | base_commit + test_patch (failing) + interface hint | Implement API to make tests pass | Pass@1 (F2P + P2P) |

- **F2P (Fail-to-Pass)**: Test node IDs that fail before the fix and pass after
- **P2P (Pass-to-Pass)**: Baseline tests that must remain passing (regression check)

## Project Structure

```
swe-paddle/
├── collect/                # Data collection pipeline
│   ├── crawl_historical.py
│   ├── fetch_historical_prs.py
│   ├── extract_problem_statement.py
│   └── classify_llm.py
├── dataset/                # All JSONL datasets
├── harness/                # Three-run verification framework
│   ├── run_pilot.py
│   ├── docker_env.py
│   ├── build_paddle.py
│   └── config.py
├── DESIGN.md               # Full design document (with paper survey)
└── PROGRESS.md             # Progress tracking
```

## Status

The dataset is collected and classified. The remaining gap is **three-run verification** (F2P/P2P extraction), which requires a GPU Docker environment with the PaddlePaddle CI image.

## License

This project uses data from [PaddlePaddle/Paddle](https://github.com/PaddlePaddle/Paddle) (Apache 2.0) and [PaddlePaddle/community](https://github.com/PaddlePaddle/community).
