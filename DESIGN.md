# PaddleSWE-Bench：基于飞桨黑客松的 Coding Agent Benchmark

## Context

飞桨黑客松（PaddlePaddle Hackathon）历届积累了大量高质量的开发任务：每个任务有结构化的描述（详细说明+验收标准+技术要求+参考资料），且已完成的任务有对应的 merged PR。这些数据天然构成 SWE-bench 的三元组：`(issue, repo_snapshot, gold_patch)`。

目标：构建一个吸取 SWE-bench 系列最新研究成果（SWE-bench Pro / SWE-ABS / SWE-Bench+ / Multi-SWE-bench / SWE-bench Live）的高质量 Paddle 专属 benchmark。

---

## 一、可行性结论：YES

### 数据基础（第 9 期实测）

| 指标 | 数值 |
|------|------|
| 第 9 期个人挑战赛总任务 | 128 |
| 已完成任务 | 88 |
| 有 code+test 的 PR（可提取 F2P） | 71% (10/14 Paddle PR) |
| 历届黑客松（4th~9th） | 6 期 |
| **预估有效样本** | **~220**（与 SWE-bench Verified 500 同量级） |

### 核心优势

1. **任务描述质量极高**：结构化（详细描述+验收说明+技术要求+参考资料），天然接近 SWE-bench Pro 的人工增强效果
2. **C++/CUDA 内核修改**：SWE-bench 全 Python，Multi-SWE-bench 有 C/C++ 但无 CUDA
3. **天然难度分级**：0.025🌟~3🌟
4. **数据污染风险低**：中文描述 + 非主流训练数据源
5. **答案泄露风险低**：出题方撰写描述（非 GitHub issue 讨论），不含解法代码

---

## 二、论文调研：SWE-bench 系列的已知问题 & 最佳实践

### 核心问题汇总

| 问题 | 来源论文 | 严重程度 | PaddleSWE 风险 |
|------|----------|----------|----------------|
| 答案泄露（32.67% issue 含解法） | SWE-Bench+ | 致命 | **低**（出题方撰写，非社区讨论） |
| 测试太弱（19.78% 通过 patch 语义错误） | SWE-ABS | 致命 | **同样存在**（PR 测试 = 验证特定修复） |
| 数据污染（94% 在训练截止前） | SWE-Bench+ | 高 | **较低**（中文 + 新数据） |
| 复杂度不足（32% 是 1-2 行修改） | SWE-bench Pro | 中 | **可控**（设最低 LOC 门槛） |
| 测试 flaky | 多篇 | 中 | **需处理**（三次运行去 flaky） |
| 只验功能不验设计 | Design-aware eval | 中 | **可扩展** |

### 各论文最佳实践 → PaddleSWE 采纳方案

**从 Multi-SWE-bench 采纳：三次运行验证（核心方法论）**

```
对每个 PR，在 Docker 中三次运行：

Run.log  = base_commit 原始状态运行测试
Test.log = base_commit + test_patch 运行测试
Fix.log  = base_commit + test_patch + code_patch 运行测试

追踪每个测试用例的状态转换三元组：
  PASSED → FAILED → PASSED  ✓ = FAIL_TO_PASS（bug 修复类）
  NONE   → FAILED → PASSED  ✓ = FAIL_TO_PASS（新增测试类）
  PASSED → PASSED → PASSED  ✓ = PASS_TO_PASS（回归保护）
  ANY    → PASSED → FAILED  ✗ = 引入回归，丢弃
  ANY    → FAILED → FAILED  ✗ = 修复无效，丢弃

Multi-SWE-bench 用此方法从候选中筛出 66.5% 有效样本
```

**从 SWE-bench Pro 采纳：质量控制措施**

1. **三次运行去 flaky**：每组测试跑 3 遍，不一致则丢弃
2. **最低复杂度门槛**：gold_patch ≥ 5 LOC（Paddle 任务普遍较大，可放低于 Pro 的 10 LOC）
3. **接口规范（可选）**：对需要新建类/函数的任务，提供 agent 需实现的接口签名 → 减少假阴性
4. **每仓库上限**：防止某类任务过多导致过拟合（如 0-Size 修复类限 5 个代表样本）

**从 SWE-ABS 采纳：测试质量提升（进阶优化）**

1. **test decoupling**：检查测试是否过度耦合 gold_patch（硬编码错误信息等） → 泛化测试
2. **mutation testing 验证**：对 gold_patch 生成语义变异版 → 验证测试能否区分正确和错误实现
3. 报告双指标：`resolve_rate`（标准）+ `strict_resolve_rate`（增强测试后）
4. SWE-ABS 成本 $4.98/样本，220 个样本约 $1,100

**从 SWE-Bench+ 采纳：答案泄露审查**

1. 构建两版 problem_statement：
   - `full`：完整描述（含验收说明+技术要求+参考资料）
   - `minimal`：只保留"完成 X 问题修复"概要 + 验收条件
2. 人工审查 full 版本中是否包含：文件路径、函数名、代码片段、diff 示例

**从 SWE-bench Live 采纳：环境自动化**

1. **RepoLaunch 思路**：用 LLM agent 从 CI 配置自动生成 Dockerfile（Paddle 有标准化的 CI，可复用）
2. **Time-machine 机制**：pip index proxy 只提供 base_commit 时间戳之前的包版本（防止依赖漂移）

---

## 三、数据收集流水线（6 步）

### Step 1: 解析黑客松任务表格

```
输入: 各期 Overview Issue (e.g., #74773, #74774, #76333 等)
处理: 正则解析 markdown 表格
输出 tasks.jsonl:
  {task_number, task_title, difficulty, PR_urls[], status, assignee, hackathon_edition}
```

### Step 2: 爬取任务详细描述

```
输入: PaddlePaddle/community 仓库的任务合集 md
处理: 按 ### NO.X 分割, 提取:
  - problem_statement_full: 详细描述 + 验收说明 + 技术要求 + 参考资料
  - problem_statement_minimal: 仅概要描述 + 验收条件
  - acceptance_criteria: 验收说明单独抽取
```

### Step 3: 爬取 PR 信息

```
输入: PR_urls
处理: GitHub API 获取:
  - base_commit SHA (merge_base)
  - merged 状态
  - full diff (.diff URL)
  - changed_files, additions, deletions
过滤: 仅保留 merged=True
```

### Step 4: 分离 patch

```
以 PR #74831 (fix index_add 0-size) 为例:

  code 文件:
    paddle/phi/kernels/cpu/index_add_grad_kernel.cc      ─┐
    paddle/phi/kernels/gpu/index_add_grad_kernel.cu        ├→ code_patch
    paddle/phi/kernels/index_add_kernel_impl.h            ─┘

  test 文件:
    test/legacy_test/test_index_add_op.py                 ─→ test_patch

用 unidiff 库按路径分离:
  test_patch 路径匹配（Paddle 定制）:
    test/**/*.py, *_test.py, test_*.py, *_test.cc, *_test.cu, tests/
  code_patch: 其余文件

过滤: 必须同时有 code_patch 和 test_patch（第 9 期实测 71% 满足）
过滤: code_patch ≥ 5 LOC（排除 trivial）
```

### Step 5: 三次运行验证（核心 —— 采纳 Multi-SWE-bench 方法论）

```
在 Docker 中对每个样本执行三次运行:

  Run 1 (Run.log):  checkout base_commit → 运行相关测试
  Run 2 (Test.log): checkout base_commit + apply test_patch → 运行测试
  Run 3 (Fix.log):  checkout base_commit + apply test_patch + apply code_patch → 运行测试

每次运行重复 3 遍（去 flaky, 采纳 SWE-bench Pro）

构造 FAIL_TO_PASS:
  = Test.log 中 FAILED 且 Fix.log 中 PASSED 的测试用例集合

构造 PASS_TO_PASS:
  = Run.log 中 PASSED 且 Fix.log 中 PASSED 的测试用例集合

丢弃条件:
  - FAIL_TO_PASS 为空（test_patch 在 base 上就 pass → 纯补测试类，不适合评测）
  - Fix.log 中有 FAILED（gold patch 不能让所有新测试 pass → 数据有问题）
  - 三次运行结果不一致（flaky test）
```

#### 具体示例：PR #74831 (fix index_add 0-size)

**Step 4 分离 patch**：PR 修改了 4 个文件

```
code_patch (3 个文件):
  paddle/phi/infermeta/binary.cc                    (+25 行, 0-size infermeta 处理)
  paddle/phi/kernels/gpu/index_add_grad_kernel.cu   (+24 行, grad 0-size 分支)
  paddle/phi/kernels/gpu/index_add_kernel.cu        (+12 行, forward 0-size 分支)

test_patch (1 个文件):
  test/legacy_test/test_index_add_op.py             (+35 行, 新增 TestIndexAdd_ZeroSize2)
    → class TestIndexAdd_ZeroSize2(OpTest)  ← 用 index=[] (空数组) 测试 0-size
      → def test_check_output()
      → def test_check_grad_normal()
```

**Step 5 三次运行**：

```
Run 1 (Run.log): git checkout base_commit → pytest test_index_add_op.py
  TestIndexAdd::test_check_output           → PASSED
  TestIndexAdd_ZeroSize::test_check_output  → PASSED
  TestIndexAdd_ZeroSize2                    → 不存在 (NONE)

Run 2 (Test.log): git checkout base_commit + apply test_patch → pytest
  TestIndexAdd::test_check_output           → PASSED (不受影响)
  TestIndexAdd_ZeroSize::test_check_output  → PASSED
  TestIndexAdd_ZeroSize2::test_check_output → FAILED ← 新测试! kernel 还没修, 崩溃
  TestIndexAdd_ZeroSize2::test_check_grad   → FAILED ← 同上

Run 3 (Fix.log): git checkout base_commit + apply test_patch + apply code_patch → pytest
  TestIndexAdd::test_check_output           → PASSED
  TestIndexAdd_ZeroSize::test_check_output  → PASSED
  TestIndexAdd_ZeroSize2::test_check_output → PASSED ← kernel 修了, 通过!
  TestIndexAdd_ZeroSize2::test_check_grad   → PASSED
```

**状态转换三元组 → 分类**：

```
测试                                  Run→Test→Fix    归类
───────────────────────────────────────────────────────────
TestIndexAdd::test_check_output       P → P → P       PASS_TO_PASS
TestIndexAdd_ZeroSize::test_output    P → P → P       PASS_TO_PASS
TestIndexAdd_ZeroSize2::test_output   N → F → P       FAIL_TO_PASS ★
TestIndexAdd_ZeroSize2::test_grad     N → F → P       FAIL_TO_PASS ★
```

**最终样本**：
```python
{
    "instance_id": "PaddlePaddle__Paddle-74831",
    "problem_statement": "完成 paddle.index_add 0-Size 问题修复",
    "FAIL_TO_PASS": [
        "test_index_add_op::TestIndexAdd_ZeroSize2::test_check_output",
        "test_index_add_op::TestIndexAdd_ZeroSize2::test_check_grad_normal"
    ],
    "PASS_TO_PASS": [
        "test_index_add_op::TestIndexAdd::test_check_output",
        "test_index_add_op::TestIndexAdd_ZeroSize::test_check_output"
    ]
}
```

**评测时**：agent 拿到 base_commit + test_patch（新测试存在但 fail），需自行修复 kernel 让测试 pass。

### Step 5 补充：F2P/P2P 提取的关键问题

#### 问题 1: 运行哪些测试？

不能跑整个 test suite（太慢 + 无关测试会引入噪声）。确定"相关测试"的策略：

```
策略 A（首选）: 从 test_patch 中提取
  - test_patch 修改/新增了哪些测试文件 → 直接跑这些文件
  - 例: test_patch 修改了 test_index_add_op.py → 跑这个文件
  - 优点: 精确、快速
  - 缺点: 只有有 test_patch 的样本能用

策略 B（补充）: 基于 code_patch 反向查找
  - code_patch 修改了 paddle/phi/kernels/gpu/index_add_kernel.cu
  - 查找 Paddle CI 配置或 CMakeLists 中哪些测试依赖这个文件
  - 或按命名规则: index_add → test_index_add_op.py
  - 用于没有 test_patch 但有关联测试的样本

策略 C（用于 Track C Feature Impl）: 从 gold_patch 的测试文件推断
  - gold_patch 完整 diff 中包含的测试文件 = 相关测试
  - 这些测试在 agent 实现前应该 FAIL（因为被测功能不存在）
```

#### 问题 2: 没有 test_patch 的 code_only 样本怎么办？

当前第 9 期有 8 个 code_only 样本（精度修复类居多）。处理策略：

```
情况 1: 修改的是 PFCCLab/PaddleAPITest 仓库
  - 这个仓库本身就是 "测试仓库"
  - 修改的文件（如调整 tolerance）就是测试文件
  - 方案: 整个 patch 视为 test_patch，code_patch 为空 → 不适合 Track A
  - 归类: 排除（或归入 "测试维护" 类，不纳入评测）

情况 2: 修改的是 Paddle 主仓库但 PR 没写新测试
  - 可能原因: 修复较小，依赖现有测试覆盖
  - 方案 A: 用策略 B 找现有相关测试，看 code_patch 是否让某些现有测试结果变化
  - 方案 B: 排除（保守策略，保证数据质量）
  - 推荐: Pilot 阶段先排除，后续如果样本量不够再补救
```

#### 问题 3: FAIL_TO_PASS 为空的情况

```
可能原因:
  1. test_patch 新增的测试在 base_commit 上就 PASS → 测试写得有问题（不依赖 code fix）
  2. 测试需要 code_patch 的部分才能 import/编译 → apply test_patch 后直接 ERROR 而非 FAIL

处理:
  - 原因 1: 丢弃（测试质量不足）
  - 原因 2: 区分 FAILED 和 ERROR，两者都可作为 FAIL_TO_PASS 候选
    (SWE-bench 的做法: ImportError/ModuleNotFoundError 视为 FAILED)
```

#### 问题 4: Paddle 编译问题

```
Paddle 是 C++/CUDA 项目，code_patch 可能修改了 .cc/.cu 文件。
三次运行时:
  - Run 1 和 Run 2 不 apply code_patch → 不需要重编译（用预编译 wheel）
  - Run 3 apply code_patch → 需要增量编译修改的 .cc/.cu 文件

解决方案:
  A. 纯 Python 测试层（大部分 Paddle 测试）:
     - 使用 Paddle 预编译 wheel + 替换 .py 文件即可
     - 不涉及编译

  B. C++/CUDA kernel 修改:
     - 方案 1: 用 Paddle 的 custom_device 或 JIT 编译机制（部分算子支持）
     - 方案 2: Docker 中预装编译环境，增量编译 + 替换 .so
     - 方案 3: 使用与 base_commit 最近的 nightly wheel，只测 Python 层行为
     - 推荐: 使用 Paddle 官方 CI Docker 镜像（已含编译环境），跑增量编译

  实际操作（Pilot 阶段简化版）:
     1. docker pull paddlepaddle/paddle:latest-dev-cuda12.3-cudnn9
     2. git checkout base_commit
     3. cmake + make（只编译相关 target，约 5~15 min）
     4. 运行 pytest
```

### Step 5.5: 任务自动分类规则

```python
def classify_task(task: dict, instance: dict) -> str:
    """基于任务标题和 patch 特征自动分类"""
    title = task["task_title"]
    repo = instance["repo"]

    # Rule 1: FastDeploy 测试任务
    if repo == "PaddlePaddle/FastDeploy":
        if instance["has_test_patch"] and not instance["has_code_patch"]:
            if "自定义算子" in title or "算子" in title:
                return "TG_operator"   # Track B: 算子单测
            else:
                return "TG_module"     # Track B: 模块单测

    # Rule 2: Bug Fix 类（关键词匹配）
    bug_keywords = ["修复", "fix", "0-Size", "0-size", "精度", "precision",
                    "bug", "error", "crash", "问题"]
    if any(kw in title.lower() for kw in bug_keywords):
        return "BF"                    # Track A: Bug Fix

    # Rule 3: Feature Implementation 类
    feature_keywords = ["新增", "实现", "开发", "添加", "支持", "implement",
                        "add", "新 API", "新增 API"]
    if any(kw in title for kw in feature_keywords):
        return "FI"                    # Track C: Feature Implementation

    # Rule 4: Feature Enhancement 类
    enhance_keywords = ["优化", "增强", "改进", "完善", "升级", "enhance",
                        "improve", "optimize"]
    if any(kw in title for kw in enhance_keywords):
        return "FE"                    # Track C variant

    # Default: 根据 patch 特征判断
    if instance["has_code_patch"] and instance["has_test_patch"]:
        return "BF"  # 有 code+test 默认归为 bug fix
    elif instance["has_test_patch"] and not instance["has_code_patch"]:
        return "TG_other"
    else:
        return "UNKNOWN"
```

### Step 6: 最终过滤 & 质量审查

```
自动过滤:
  - 纯文档/配置修改 → 排除
  - FAIL_TO_PASS 为空 → 排除
  - code_patch < 5 LOC → 排除
  - 同类任务去重（如 0-Size 修复保留 ≤5 个代表样本）

人工审查（参考 Multi-SWE-bench 的人工验证）:
  - problem_statement 是否清晰、无歧义
  - 测试覆盖是否足够（能区分正确和错误实现）
  - 是否存在答案泄露（描述中含具体文件名/函数名/代码片段）
```

---

## 三点五、核心概念：gold patch 的作用

**问: PR 的 gold patch (code_patch) 是不是没啥用？核心是 F2P/P2P？**

答: gold patch 有用，但不参与评分。它的作用是：

```
┌─────────────────────────────────────────────────────────┐
│ 数据构建阶段（我们做的）                                   │
│                                                         │
│  gold patch 用途:                                       │
│  1. Run 3 的输入 → 证明 F2P 测试确实可修复（排除无解样本）  │
│  2. 计算 gold_patch_loc → 难度分级                       │
│  3. 提取 Interface 字段（Track C）                        │
│  4. 作为分析参考（语言分布、文件数等）                       │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ Agent 评测阶段（实际跑 benchmark）                        │
│                                                         │
│  agent 拿到:                                            │
│    - base_commit + test_patch 已 apply（F2P 测试存在但 fail）│
│    - problem_statement                                  │
│    - (可选) hints_text / interface                       │
│                                                         │
│  agent 输出: predicted_patch                            │
│                                                         │
│  评分: 跑 F2P 测试                                      │
│    - F2P 全 pass + P2P 无回归 → resolved ✓              │
│    - 否则 → unresolved ✗                                │
│                                                         │
│  注意: 不对比 predicted_patch 和 gold patch 的相似度！     │
│  一个完全不同的修复方式只要让测试通过就算对。                  │
└─────────────────────────────────────────────────────────┘

所以核心确实是 F2P/P2P:
  - 没有 F2P → 无法自动评分 → 样本无效
  - gold patch → 只是验证数据有效性的工具
  - 评测时 gold patch 完全不可见
```

---

## 四、每个样本的字段

```python
{
    # === 对齐 SWE-bench 标准字段 ===
    "instance_id": "PaddlePaddle__Paddle-74831",
    "repo": "PaddlePaddle/Paddle",
    "base_commit": "abc123...",
    "patch": "diff --git a/paddle/phi/...",            # gold patch (code only)
    "test_patch": "diff --git a/test/...",             # test changes
    "problem_statement": "完成 paddle.index_add ...",  # minimal 版
    "hints_text": "参考资料: ...",                      # full 版的额外信息
    "FAIL_TO_PASS": ["test_index_add_op.py::TestIndexAdd0Size::test_0size_cpu"],
    "PASS_TO_PASS": ["test_index_add_op.py::TestIndexAdd::test_basic"],
    "created_at": "2025-08-20T...",

    # === PaddleSWE 分类 & 评测字段 ===
    "track": "A",                                      # A=BugFix, B=TestGen, C=FeatureImpl
    "task_type": "BF",                                 # BF/TG_operator/TG_module/FI/FE
    "eval_method": "pass_at_1",                        # pass_at_1 / coverage_mutation / perf_score

    # === PaddleSWE 扩展字段 ===
    "difficulty": "0.025",
    "hackathon_edition": "9th",
    "task_number": 1,
    "problem_statement_full": "...",                   # 含参考资料的完整版
    "gold_patch_loc": 15,                              # gold patch 行数
    "gold_patch_files": 3,                             # gold patch 文件数
    "language_mix": ["python", "cpp", "cuda"],         # 涉及的语言
    "interface": null,                                 # Track C only: 需实现的接口签名

    # === Track B 专用字段 ===
    "source_code_paths": [],                           # 被测算子/模块源文件路径
    "gold_test_loc": 0,                                # gold test 行数
    "test_spec_doc": "",                               # 单测开发规范文档 URL
}
```

---

## 五、Docker 评测环境

### GPU 需求分析

黑客松大部分任务涉及 CUDA kernel 修改（0-Size 修复、精度修复等），测试会调用 GPU 算子。
**三次运行验证和评测都需要 GPU 环境**（这是与 SWE-bench 纯 Python 环境最大的区别）。

| 阶段 | GPU | 说明 |
|------|-----|------|
| 数据收集（Step 1-4） | 不需要 | 爬取 + 解析 + 分离 patch |
| 三次运行验证（Step 5） | **需要** | 运行 Paddle GPU 测试 |
| Agent 评测 | **需要** | apply patch 后运行测试 |

### 镜像层级

```
Layer 1: Base Image
  paddle/paddle:X.Y.Z-gpu-cudaA.B-cudnnC + 基础依赖
  （可复用 Paddle 官方 CI Docker 镜像）

Layer 2: Env Image (per Paddle version range)
  + git clone Paddle repo
  + 安装编译/运行依赖
  + 预编译 Paddle wheel（关键优化：避免每个 instance 重编译）

Layer 3: Instance Image (per sample)
  + git checkout {base_commit}
  + apply test_patch
  + pip install 预编译 wheel（如 base_commit 在 wheel 版本范围内）
```

### 版本分桶策略

黑客松 PR 的 base_commit 通常集中在某个版本附近（同期活动基于同一 develop 分支），可按"同期黑客松"分桶，大幅减少 env image 数量。

### GPU 资源方案

1. **Paddle 官方 GPU Docker**：`paddle/paddle:X.Y.Z-gpu-cuda*-cudnn*`，自带预编译 Paddle + CUDA
2. **百度内部 GPU**：AI Studio V100 环境（黑客松本身就提供的）、或内部 GPU 集群
3. **纯 CPU 子集**：部分测试支持 CPU 模式（`@unittest.skipIf(not compiled_with_cuda)`），可单独划出一个不需要 GPU 的子集用于快速验证
4. **云 GPU 按需**：验证阶段（一次性）和评测阶段（按需）分开预算

### 测试运行

```bash
# Python 单测（大部分 Paddle 测试）
python -m pytest test/legacy_test/test_index_add_op.py::TestIndexAdd0Size -v --timeout=300

# C++ 单测（少数）
ctest --test-dir build -R test_name --output-on-failure --timeout 300
```

---

## 六、任务类型分类 & 评测框架（参考 SWE-Compass）

### 调研结论

**SWE-Compass**（快手 Kwaipilot，2025.11）是目前唯一对不同任务类型采用**不同评测指标**的 benchmark：

| 任务类型 | 评测指标 |
|----------|----------|
| Feature Implementation (FI) | Pass@1（test-based） |
| Feature Enhancement (FE) | Pass@1 |
| Bug Fixing (BF) | Pass@1 |
| Refactoring (RF) | Pass@1 |
| Performance Optimization (PO) | Performance Score（通过测试 + 执行时间 < 80% 基准） |
| Test Case Generation (TG) | Line Coverage |
| Code Understanding (CU) | LLM-as-Judge |
| Configuration & Deployment (CD) | Pass@1 |

**SWE-bench Pro** 对 Feature Addition 类任务提供 Interface 字段（函数签名+文件路径）以减少假阴性。

### Paddle 黑客松任务 → 类型映射

| 黑客松任务类型 | 实际数据 | 映射到 SWE-Compass 类型 | 评测方法 |
|---------------|---------|------------------------|----------|
| **0-Size 问题修复** | 8 任务, 5 有 code+test | Bug Fixing (BF) | Pass@1（三次运行 FAIL_TO_PASS） |
| **精度问题修复** | 11 任务, 2 有 code+test | Bug Fixing (BF) | Pass@1 |
| **自定义算子单测补充** | 50 任务, 全 test_only | Test Case Generation (TG) | Coverage + Mutation Score |
| **功能模块单测补充** | 16 任务, 全 test_only | Test Case Generation (TG) | Coverage + Mutation Score |
| **工具/框架能力(加赛)** | 5 任务, 1 有 code+test | Feature Implementation (FI) | Pass@1 + Interface 提示 |

### 扩展到历届黑客松（预期新增类型）

| 预期类型 | 来源 | 映射 | 评测方法 |
|----------|------|------|----------|
| **新增 API 开发** | 4th~8th 常见 | Feature Implementation (FI) | Pass@1 + Interface 字段 |
| **API 功能增强** | 4th~8th 常见 | Feature Enhancement (FE) | Pass@1 |
| **性能优化** | 算子融合/kernel 优化 | Performance Optimization (PO) | Pass@1 + 性能提升比 |
| **文档/示例补充** | 部分期有 | ❌ 排除 | 不适合自动评测 |

---

## 七、三轨道设计（取代原双赛道）

### Track A: Bug Fixing（传统 SWE-bench 方向）

```
来源: 0-Size 修复 + 精度修复 + 历届 bug fix 类任务
输入: problem_statement + repo(base_commit + test_patch 已 apply)
目标: agent 生成 code_patch 让 FAIL_TO_PASS 测试通过
评判: Pass@1 = (FAIL_TO_PASS 全 pass + PASS_TO_PASS 无回归)
样本: ~7 第 9 期, 扩展后 ~50+
语言: Python + C++/CUDA
```

**数据要求**: 必须同时有 code_patch 和 test_patch，且三次运行验证通过。

### Track B: Test Case Generation（利用 FastDeploy 海量数据）

```
来源: 自定义算子单测补充 + 功能模块单测补充
输入: problem_statement + 被测算子/模块源代码 + 单测开发规范
目标: agent 为指定目标生成单测代码
评判: 多维度（见下方）
样本: ~40 第 9 期, 扩展后 ~100+
语言: Python（测试代码） + 被测 C++ 算子源码作为输入
```

**评测指标（参考 SWE-Compass TG 赛道 + SWT-Bench）**:

| 指标 | 权重 | 方法 |
|------|------|------|
| **可执行性** | 必须 | 生成的测试能跑通不报错 |
| **行覆盖率** | 40% | `coverage.py` 测量被测算子的代码覆盖 |
| **Mutation Score** | 40% | 对被测算子注入 N 个变异 → 测试能杀死多少 |
| **规范遵从** | 20% | 是否遵循 unittest 继承、断言方式、命名规范 |

**不需要三次运行验证** —— 只需验证 gold test 能跑通即可（评测成本低）。

### Track C: Feature Implementation（新增功能/API）

```
来源: 历届黑客松的 "新增 API"、"新增功能"、"算子开发" 类任务
输入: problem_statement + repo(base_commit + test_patch 已 apply) + Interface 字段
目标: agent 实现指定接口/API 让测试通过
评判: Pass@1（同 Track A）
样本: 待扩展到历届（第 9 期 ~1 个, 预期总量 ~80+）
语言: Python + C++/CUDA
特殊: 提供 Interface 字段（参考 SWE-bench Pro），包含：
  - 需实现的函数/类签名
  - 目标文件路径
  - 减少因命名差异导致的假阴性
```

**数据要求**: 同 Track A（code_patch + test_patch + 三次运行），额外需从 gold_patch 中提取 Interface 信息。

### 三轨道对比

| 维度 | Track A: Bug Fix | Track B: Test Gen | Track C: Feature Impl |
|------|-----------------|-------------------|----------------------|
| 评测能力 | 定位 + 修复 bug | 理解代码 + 写测试 | 理解需求 + 实现功能 |
| 评测指标 | Pass@1 | Coverage + Mutation | Pass@1 |
| 数据构建难度 | 高（需三次运行验证） | 低（只需 gold test 可执行） | 高（需三次运行 + Interface） |
| GPU 需求 | 必须 | 必须（跑测试） | 必须 |
| 第 9 期样本 | ~7 | ~40 | ~1 |
| 扩展后预估 | ~50 | ~100 | ~80 |
| 独特性 | CUDA kernel bug | 无同类 benchmark | 少见（APEX-SWE 类似） |

---

## 八、信息流优化：每种 Track 的 problem_statement 设计

参考 SWE-bench Pro 三阶段增强，为不同 Track 设计不同的 problem_statement 格式：

### Track A (Bug Fix): 保留结构化描述

```
[Level 1 - minimal] 修复 paddle.index_add 在 0-size tensor 输入时的运行时错误。
[Level 2 - standard] + 验收说明（哪些 case 需通过）
[Level 3 - full] + 技术要求 + 参考资料
```

### Track B (Test Gen): 提供被测对象 + 规范

```
[固定格式]
  - 被测算子名称 + API 签名
  - 被测算子源文件路径
  - 单测开发规范文档
  - 已有相似测试的范例（可选 hint）
```

### Track C (Feature Impl): 提供 Interface 字段

```
[Level 1 - minimal] 实现 paddle.Tensor.index_add_ API（in-place 版本）
[Level 2 - standard] + 验收说明 + Interface 签名
[Level 3 - full] + 技术要求 + 参考 PyTorch 实现
Interface: {
  "file": "python/paddle/tensor/manipulation.py",
  "signatures": ["def index_add_(self, dim, index, source, alpha=1.0)"]
}
```

---

## 九、与现有 benchmark 全面对比

| 维度 | SWE-bench | SWE-bench Pro | SWE-Compass | Multi-SWE | **PaddleSWE** |
|------|-----------|---------------|-------------|-----------|---------------|
| 语言 | Python | Py/JS/TS/Go | Py/TS | 7 语言 | **Py+C++/CUDA** |
| 仓库 | 12 | 41 | 56 | 39 | Paddle 生态 |
| 样本 | 2294/500V | 1865 | 1039 | 2132 | ~230 |
| 任务类型 | 不分 | 描述性标签 | **8 类+不同指标** | 不分 | **3 Track+不同指标** |
| 描述质量 | 原始 issue | 三阶段增强 | 原始 | 原始 | **结构化** |
| 泄露风险 | 高(33%) | 低 | 未评估 | 未评估 | **低** |
| 测试质量 | 弱(31%) | 多阶段验证 | 三次运行 | 三次运行 | **三次运行** |
| 污染风险 | 高(94%) | 低 | 未评估 | 未评估 | **较低** |
| 难度分级 | 无 | 有 | 无 | 时间估计 | **星级** |
| GPU 环境 | 无 | 无 | 无 | 无 | **CUDA Docker** |
| Test-Gen 轨道 | 无 | 无 | **有** | 无 | **有** |

**PaddleSWE 的独特定位**:
1. 唯一覆盖 **CUDA kernel** 修改的 SWE-bench 类 benchmark
2. 参考 SWE-Compass 引入 **任务类型分类 + 差异化评测指标**
3. 利用黑客松结构化描述，天然接近 SWE-bench Pro 的增强效果
4. 数据污染风险极低（中文 + 非主流训练数据）

---

## 十、可行性验证 Pilot

### Phase 1: Track A (Bug Fix) — 第 9 期 7 个 code+test 样本

```
1. 数据收集（已完成 Step 1-4）
   → 验证: 7 个样本的 instance_id、patch、test_patch ✓

2. Docker 三次运行验证
   → 验证: FAIL_TO_PASS 在 Test.log 中确实 fail、在 Fix.log 中确实 pass
   → 丢弃 flaky 样本

3. 端到端评测
   → 验证: 用 Claude/GPT-4o 在 3 个样本上 → 判定 resolved/unresolved

4. 评估扩展
   → 扩展到 4th~8th 期的 bug fix 类任务
```

### Phase 2: Track B (Test Gen) — 第 9 期 40 个 test_only 样本

```
1. 构建评测框架
   → 验证: gold test 在 base_commit 上能跑通
   → 搭建 coverage + mutation 评测 pipeline

2. 端到端评测
   → 验证: agent 生成测试 → 计算 coverage/mutation score

3. 评估扩展
   → 扩展到历届 FastDeploy/其他仓库的测试任务
```

### Phase 3: Track C (Feature Impl) — 扩展到历届黑客松

```
1. 爬取 4th~8th 期任务
   → 识别 "新增 API / 新增功能" 类任务
   → 提取 Interface 字段

2. 三次运行验证 + 评测
```

### 关键风险验证点

| 验证项 | 成功标准 | 当前状态 |
|--------|----------|----------|
| Track A: test_patch 在 base 上 fail | >80% | 待 Docker 验证 |
| Track A: 三次运行无 flaky | >90% | 待验证 |
| Track B: gold test 可执行 | >90% | 待验证 |
| Track B: mutation testing 可行 | 能生成变异 | 待验证 |
| Track C: 历届数据量 | >50 个 FI 类任务 | 待爬取 |

### 预期产出

```
paddleswe/
├── collect/                # 数据收集
│   ├── parse_hackathon.py        # Step 1: 解析任务表格（已完成）
│   ├── fetch_and_split.py        # Step 2-4: 爬取+分离（已完成）
│   ├── classify_tasks.py         # NEW: 自动分类任务类型
│   └── extract_interface.py      # NEW: 从 gold_patch 提取 Interface
├── dataset/                # JSONL 数据集
│   ├── track_a_bugfix.jsonl
│   ├── track_b_testgen.jsonl
│   └── track_c_feature.jsonl
├── harness/                # Docker 评测环境
│   ├── Dockerfile.paddle-gpu
│   ├── run_three_pass.py         # 三次运行验证
│   ├── eval_bugfix.py            # Track A: Pass@1 评测
│   ├── eval_testgen.py           # Track B: Coverage + Mutation 评测
│   └── eval_feature.py           # Track C: Pass@1 + Interface 评测
└── analysis/
    ├── leakage_check.py
    └── task_type_stats.py        # NEW: 类型分布统计
```
