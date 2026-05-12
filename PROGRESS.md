# PaddleSWE-Bench 项目进展

## 一句话定位

基于飞桨黑客松 6th~9th 期任务（结构化描述 + merged PR），构建类 SWE-bench 的 Coding Agent Benchmark，覆盖 Bug Fix / Test Gen / Feature Impl 三个赛道。

## 数据现状（2025-05-09 更新）

| 数据集 | 样本数 | 说明 |
|--------|--------|------|
| `tasks_6to9.jsonl` | 164 | 6th~9th 期已完成任务（含"完成任务"badge） |
| `instances_6to9.jsonl` | 133 | 已获取 PR diff + problem_statement |
| `track_a_bugfix_6to9.jsonl` | 10 | Bug Fix (0-Size/精度修复/fold bug, 主要 9th) |
| `track_b_testgen_6to9.jsonl` | 37 | Test Gen (FastDeploy 自定义算子单测, 9th) |
| `track_c_feature_6to9.jsonl` | 57 | Feature Impl (31 FI + 26 FE, 主要 6th/7th) |
| `excluded_6to9.jsonl` | 29 | 排除（迁移23 + 编译5 + 琐碎1） |

### PR 获取统计

- 163 个唯一 PR 尝试获取（91 Paddle + 42 FastDeploy + 30 跳过）
- 133 个成功获取
- 74 个同时有 code_patch + test_patch（Track A/C 最佳候选）
- 37 个 test_only（Track B）
- 20 个 code_only（部分可排除或补救）

## 三轨道评测设计

| Track | 输入 | 目标 | 评测指标 | 当前样本 |
|-------|------|------|----------|----------|
| **A: Bug Fix** | base_commit + test_patch(fail) + problem_statement | 生成 code_patch 让测试 pass | Pass@1 (F2P + P2P) | 10 |
| **B: Test Gen** | 被测算子源码 + 规范 | 为算子生成单测 | Coverage + Mutation Score | 37 |
| **C: Feature Impl** | base_commit + test_patch(fail) + Interface 提示 | 实现 API 让测试 pass | Pass@1 (F2P + P2P) | 57 |

## 核心流程

```
已完成:
  ✅ 论文调研 (SWE-bench Pro/ABS/Compass/Multi-SWE 等)
  ✅ 第 9 期数据收集 (parse → fetch → split → classify)
  ✅ 6th~9th 期正确 issue 爬取 (#62905/#68244/#71310/#74773)
  ✅ PR diff 批量获取 (133 instances, Paddle + FastDeploy)
  ✅ problem_statement 爬取 (从 community 仓库 markdown, 132/133 匹配)
  ✅ LLM-based 分类 (Track A: 10, Track B: 37, Track C: 57, Excluded: 29)

待完成:
  ⬜ 三次运行验证 → 提取 F2P/P2P (需 GPU Docker)
  ⬜ Track B 评测框架 (coverage + mutation pipeline)
  ⬜ Track C Interface 字段提取 (从 gold_patch 中提取函数签名)
  ⬜ 质量审查 (去重、泄露检查、flaky 过滤、min LOC 门槛)
  ⬜ 端到端 Pilot (选 3 个样本跑通全流程)
```

## 关键卡点

**三次运行验证 (F2P/P2P 提取)** — "raw data" → "可评测 benchmark" 的唯一缺口：
- 需要 GPU Docker 环境 (Paddle 官方 CI 镜像)
- 对每个样本执行: base+test_patch → 确认 fail; base+test_patch+code_patch → 确认 pass
- 预估有效率 ~80%

## 已知质量问题

1. **Track A 样本少**: 仅 10 个 bug fix，其中 2 个 code-only（#74863/#74854）不能直接做 F2P
2. **Track C 低质量**: #65205(1 LOC)、#64504(文档型) 应排除
3. **8th/9th 期 task_title 乱码**: crawl 解析表格时抓到了难度列，已用 pr_title 替代

## 独特卖点 (vs 现有 benchmark)

1. **唯一覆盖 CUDA kernel** 的 SWE-bench 类 benchmark
2. **任务类型分类 + 差异化评测指标** (参考 SWE-Compass)
3. **结构化描述** 天然接近 SWE-bench Pro 的增强效果
4. **数据污染风险极低** (中文 + 非主流训练数据)
5. **现有 benchmark 无 PaddlePaddle** 覆盖

## 文件结构

```
paddleswe/
├── DESIGN.md                            # 完整方案 (含论文调研、详细设计)
├── PROGRESS.md                          # 本文件
├── collect/
│   ├── parse_hackathon.py               # 解析第 9 期任务表格
│   ├── fetch_and_split.py               # 爬取+分离 patch (第 9 期)
│   ├── classify_tasks.py                # 分类任务类型 (支持 --input/--suffix)
│   ├── crawl_historical.py              # 爬取历届任务列表
│   ├── fetch_historical_prs.py          # 批量 fetch PR diff (支持多仓库)
│   └── community/                       # PaddlePaddle/community 仓库副本
├── dataset/
│   ├── tasks_6to9.jsonl                 # 164 个 6th~9th 期已完成任务
│   ├── instances_6to9_raw.jsonl         # 133 个 PR 实例 (含 diff)
│   ├── instances_6to9.jsonl             # 133 个实例 (含 problem_statement)
│   ├── track_a_bugfix_6to9.jsonl        # Track A (10 个)
│   ├── track_b_testgen_6to9.jsonl       # Track B (37 个)
│   ├── track_c_feature_6to9.jsonl       # Track C (57 个)
│   └── excluded_6to9.jsonl             # 排除 (29 个)
├── harness/                             # 待实施: Docker 评测环境
└── analysis/                            # 待实施: 质量分析
```

## 下一步优先级

1. **Pilot 端到端验证**: 选 3 个最简单的 Track A 样本 (0-Size 修复), 搭建 GPU Docker, 跑通三次运行
2. **Track B 框架**: 37 个 FastDeploy 样本不需要三次运行, 可并行搭建 coverage 评测
3. **Track C Interface 提取**: 从 gold_patch 中提取函数签名作为 Agent 提示
4. **质量审查**: 去重、泄露检查、flaky 过滤
