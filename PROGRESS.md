# PaddleSWE-Bench 项目进展

## 一句话定位

基于飞桨黑客松 6th~9th 期任务（结构化描述 + merged PR），构建类 SWE-bench 的 Coding Agent Benchmark，覆盖 Bug Fix / Feature Impl 两个赛道。

## 数据现状（2025-05-13 更新）

| 数据集 | 样本数 | 说明 |
|--------|--------|------|
| `tasks_6to9.jsonl` | 164 | 6th~9th 期已完成任务（含"完成任务"badge） |
| `instances_6to9_raw.jsonl` | 133 | 原始爬取结果（含 FastDeploy，未清理） |
| `instances.jsonl` | 89 | **权威数据集**：人工审核后，仅 Paddle 主框架 |
| `track_a_bugfix.jsonl` | 10 | Bug Fix (0-Size/精度/fold/reshape 修复)，含 2 条需外部测试 |
| `track_c_feature.jsonl` | 58 | Feature Impl (新增 API + 功能增强) |
| `excluded.jsonl` | 21 | 排除（代码迁移/清理类 + 无效 patch） |

### 清理操作（2025-05-12）

- 移除 42 条 FastDeploy（非 Paddle 主框架）
- 移除 5 条 revert/docs PR
- 修正 2 条 orphan fix 的 problem_statement（#65639, #70102）
- 新增 3 条 9th 冲刺赛数据（#76387, #76873, #77103）
- 全部条目添加 rfc_urls 字段（38 条有实际链接）

### 清理操作（2025-05-13）

- 移除 PR #65205 至 excluded（仅 1 行 docstring 改动，多 PR 任务尾巴，无评测价值）
- 标记 PR #74863, #74854 为 `needs_external_test`（测试在外部仓库 PaddleAPITest）
- 修复 `extract_problem_statement.py` 输出到 `instances_6to9_raw_enriched.jsonl`（不再覆盖权威数据）
- 对齐 CLAUDE.md 快速上手与实际 pipeline

## 评测设计

| Track | 输入 | 目标 | 评测指标 | 当前样本 |
|-------|------|------|----------|----------|
| **A: Bug Fix** | base_commit + test_patch(fail) + problem_statement | 生成 code_patch 让测试 pass | Pass@1 (F2P + P2P) | 10 (2 需外部测试) |
| **C: Feature Impl** | base_commit + test_patch(fail) + Interface 提示 | 实现 API 让测试 pass | Pass@1 (F2P + P2P) | 58 |

## 核心流程

```
已完成:
  ✅ 论文调研 (SWE-bench Pro/ABS/Compass/Multi-SWE 等)
  ✅ 6th~9th 期数据爬取 + PR diff 获取
  ✅ problem_statement 从 community 仓库提取
  ✅ LLM-based 分类 + 人工审核
  ✅ 数据清理 (移除 FastDeploy/revert/docs，修正 orphan fix)
  ✅ Harness 框架代码 (三次运行验证逻辑)

待完成:
  ⬜ 三次运行验证 → 提取 F2P/P2P (需 GPU Docker)
  ⬜ Track C Interface 字段提取 (从 gold_patch 中提取函数签名)
  ⬜ 质量审查 (去重、泄露检查、flaky 过滤、min LOC 门槛)
  ⬜ 端到端 Pilot (选 3 个样本跑通全流程)
```

## 关键卡点

**三次运行验证 (F2P/P2P 提取)** — "raw data" → "可评测 benchmark" 的唯一缺口：
- 需要 GPU Docker 环境 (Paddle 官方 CI 镜像)
- 对每个样本执行: base+test_patch → 确认 fail; base+test_patch+code_patch → 确认 pass
- 预估有效率 ~80%

## 独特卖点 (vs 现有 benchmark)

1. **唯一覆盖 CUDA kernel** 的 SWE-bench 类 benchmark
2. **任务类型分类 + 差异化评测指标** (参考 SWE-Compass)
3. **结构化描述** 天然接近 SWE-bench Pro 的增强效果
4. **数据污染风险极低** (中文 + 非主流训练数据)
5. **现有 benchmark 无 PaddlePaddle** 覆盖

## 文件结构

```
swe-paddle/
├── CLAUDE.md                            # 项目说明 + 快速上手
├── DESIGN.md                            # 完整方案 (含论文调研)
├── PROGRESS.md                          # 本文件
├── collect/
│   ├── crawl_historical.py              # 爬取历届任务列表
│   ├── fetch_historical_prs.py          # 批量 fetch PR diff
│   ├── extract_problem_statement.py     # 从 community markdown 提取描述
│   ├── classify_llm.py                  # LLM-based 分类
│   ├── classify_tasks.py                # 关键词分类 (legacy)
│   └── community/                       # PaddlePaddle/community 副本 (.gitignore)
├── dataset/
│   ├── instances.jsonl                  # 89 条权威数据集
│   ├── track_a_bugfix.jsonl             # Track A (10)
│   ├── track_c_feature.jsonl            # Track C (59)
│   ├── excluded.jsonl                   # Excluded (20)
│   ├── instances_6to9_raw.jsonl         # 原始爬取 (133, 含 FastDeploy)
│   └── tasks_6to9.jsonl                 # pipeline 输入 (164 任务)
├── harness/                             # 三次运行验证框架
│   ├── run_pilot.py                     # 主流程
│   ├── build_paddle.py                  # 源码编译管理
│   ├── docker_env.py                    # Docker 容器操作
│   └── config.py                        # 配置 + 数据结构
└── analysis/                            # 质量分析
```

## 下一步优先级

1. **Pilot 端到端验证**: 选 3 个最简单的 Track A 样本 (0-Size 修复), 搭建 GPU Docker, 跑通三次运行
2. **Track C Interface 提取**: 从 gold_patch 中提取函数签名作为 Agent 提示
3. **质量审查**: 去重、泄露检查、flaky 过滤
