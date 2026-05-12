# PaddleSWE Harness

验证 PaddleSWE-Bench 样本的 FAIL_TO_PASS / PASS_TO_PASS 测试数据提取工具。

## 快速使用

```bash
cd paddleswe

# Smoke test（无需 Docker，用当前已安装的 Paddle）
python -m harness.run_pilot --phase smoke

# 完整三态验证（需要 Docker）
python -m harness.run_pilot --phase full --dry-run   # 单样本 dry-run (PR 74850)
python -m harness.run_pilot --phase full             # 全部 5 个样本
python -m harness.run_pilot --phase full --pr 63302  # 指定 PR
```

## 两种执行模式

### Smoke Phase（当前环境可跑）

- 使用已安装的 Paddle 版本
- 提取候选 test nodeids（通过 diff parser 或 collect-only delta）
- 验证测试文件可执行
- **不构成 F2P/P2P 验证证据**，仅用于数据质量检查

产出：`dataset/pilot_smoke_nodeids.jsonl`

### Full Phase（需 Docker 宿主机）

- 每个样本在独立 Docker 容器中执行
- 完整 Run/Test/Fix 三态验证
- 产出可靠的 FAIL_TO_PASS 和 PASS_TO_PASS

产出：`dataset/mixed_pilot_verified_5.jsonl`

## 环境要求

### Smoke Phase
- Python 3.10+
- PaddlePaddle GPU（任意版本，用于 smoke 测试）
- pytest
- git（用于 clone Paddle repo 获取测试文件）
- 网络代理：`export https_proxy=http://agent.baidu.com:8891`

### Full Phase（三态验证）
- Docker（必须在宿主机上，不支持 DinD）
- GPU 驱动 + nvidia-docker2
- 网络代理
- 约 50GB 磁盘空间（Paddle 源码 + 编译产物）

## 文件说明

| 文件 | 功能 |
|------|------|
| `config.py` | 配置常量、路径、数据类定义 |
| `patch_utils.py` | Unified diff 解析、`git apply`、文件类型分类 |
| `nodeid_extractor.py` | Nodeid 提取：collect-only delta（主）+ diff parser（fallback） |
| `test_runner.py` | pytest 执行和结果解析 |
| `build_paddle.py` | Paddle 源码编译（全量/增量），产出并安装本地 wheel |
| `docker_env.py` | Docker 容器管理、镜像选择、preflight 检查 |
| `result_recorder.py` | JSONL 结果输出 |
| `run_pilot.py` | CLI 编排入口 |

## Pilot 样本

Mixed Track A/C pilot（5 个样本）：

| instance_id | Track | 题面 | code 类型 |
|-------------|-------|------|-----------|
| Paddle-74850 | A | batch_norm 0-Size | `.cc` (需编译) |
| Paddle-74851 | A | fused_layer_norm 0-Size | `.cc` (需编译) |
| Paddle-63302 | C | AdaptiveLogSoftmaxWithLoss | 纯 Python |
| Paddle-64519 | C | cholesky_inverse | 纯 Python |
| Paddle-63728 | C | ZeroPad1D/ZeroPad3D/block_diag | 纯 Python |

## Run/Test/Fix 三态验证逻辑

```
Run态:  checkout base_commit → 收集原始 nodeids → 执行 baseline
Test态: apply test_patch → 运行测试 → 期望新增 nodeids FAIL
Fix态:  apply code_patch → [增量编译] → 运行测试 → 期望 PASS
```

- FAIL_TO_PASS = Test 态 FAIL ∩ Fix 态 PASS
- PASS_TO_PASS = Run 态 PASS ∩ Fix 态 PASS（baseline nodeids 未回归）

## 输出格式

Smoke 结果（`pilot_smoke_nodeids.jsonl`）：
```json
{"instance_id": "...", "smoke_status": "PASS", "candidate_nodeids": [...], "is_verified": false}
```

Verified 结果（`mixed_pilot_verified_5.jsonl`）：
```json
{"instance_id": "...", "FAIL_TO_PASS": [...], "PASS_TO_PASS": [...], "test_status": "CONFIRMED_FAIL", "fix_status": "CONFIRMED_PASS"}
```

## 注意事项

- 当前 paddlejob 容器环境缺少 NET_ADMIN/iptables，**无法运行 Docker-in-Docker**
- Smoke phase 使用 diff parser fallback（因为 HEAD 已包含 test_patch 修改，git apply 会失败）
- 完整验证必须在有 Docker 的宿主机上执行
- 纯 Python 样本使用 wheel + PYTHONPATH overlay 策略保证 base_commit 语义
- `.cc` 样本需要全量源码编译（首次约 60-90min），Fix 态增量编译 + 重装 wheel
