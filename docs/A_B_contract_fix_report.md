# A/B Integration Contract 修复与测试报告

**日期：** 2026-08-31  
**修复分支：** `fix/a-b-integration-contracts`  
**基线：** 最新 `main`（已包含 Engineer A 与 Engineer B 模块）

## 1. 检查背景

Engineer B 的 `state.py`、`policy.py` 与测试合入后，仓库原有测试为：

```text
65 passed in 0.36s
```

单模块测试均通过，但进一步检查 A/B 的实际调用契约后，发现两个跨模块问题：

1. B 输出的预算类型被 A 错误统一解释为预算上限；
2. B 的 Information Gain policy 无法正确读取 shared `Candidate`。

这两个问题都属于单模块测试无法充分发现的 integration-contract 问题。

## 2. 问题一：Budget 语义被错误转换

### 2.1 B 的输出

B 会保留三种不同预算语义：

```text
max:40
min:25
target:50
```

含义分别是：

- `max:40`：最高预算 40；
- `min:25`：最低预算 25；
- `target:50`：目标价格约为 50。

### 2.2 原有错误

A 的 `_budget_ceiling()` 会提取任意 budget 字符串中的数字，并全部当成最高预算：

```text
min:25    -> ceiling 25
target:50 -> ceiling 50
max:40    -> ceiling 40
```

因此：

- “至少 25”会被错误理解为“不超过 25”；
- “目标价格 50”会被错误理解为“不超过 50”；
- 高于错误 ceiling 的商品会被错误扣分。

### 2.3 修复方式

`src/retrieval.py` 现在只从明确的 upper-bound 表达中生成 ceiling：

```text
max:40
under $40
below $40
less than $40
up to $40
at most $40
no more than $40
{"max": 40}
```

以下值不再被解释为 ceiling：

```text
min:25
target:50
```

当前排序行为为：

- 明确超过最高预算：保留现有 soft penalty；
- 最低预算和目标价格：不再错误使用最高预算 penalty；
- 缺失价格：继续保持中性。

本次修复没有取消合理的负向约束或超预算惩罚。

## 3. 问题二：Information Gain 无法读取真实 Candidate

### 3.1 Shared Candidate contract

项目共享类型为：

```python
@dataclass(slots=True)
class Candidate:
    parent_asin: str
    score: float
    search_text: str
    product: dict
    route_ranks: dict[str, int]
```

因为使用了 `slots=True`，`Candidate` 没有 `__dict__`。

### 3.2 原有错误

B 的 `QuestionPolicy._attribute_values()` 原来通过：

```python
candidate.__dict__
```

读取候选数据。对于真实 shared `Candidate`，这会退化为空 mapping，导致 policy 无法读取：

```python
candidate.search_text
candidate.product
```

原有 slots Candidate 测试虽然通过，但测试期望恰好等于固定 fallback 顺序的第一个属性，因此没有真正证明候选字段被读取。

### 3.3 修复方式

`src/policy.py` 现在区分两种输入：

- dictionary candidate：继续读取 mapping fields；
- object/shared Candidate：直接读取公开 contract fields。

```python
product = getattr(candidate, "product", {})
search_text = getattr(candidate, "search_text", "")
```

同时保留对可能包含 `attributes` 的其他候选对象的兼容。

新增测试使用：

```text
running shoes
hiking boots
```

其中 `use_case` 有明确 coverage/diversity，`feature` 没有。修复前 policy 错误回退到 `feature`；修复后正确选择 `use_case`。

## 4. 新增 Regression Tests

本次新增 5 个测试 case：

1. `min:25` 不得作为 ceiling；
2. `target:50` 不得作为 ceiling；
3. `max:40` 必须继续作为 ceiling；
4. `under $40` 必须继续作为 ceiling；
5. Information Gain 必须读取真实 `slots=True Candidate` 的字段。

## 5. 测试过程与结果

### 5.1 修复前

新增 regression tests 后，旧实现得到：

```text
3 failed, 2 passed
```

三个失败分别复现：

- `min:25` 被错误扣预算分；
- `target:50` 被错误扣预算分；
- Information Gain 无法读取真实 slots Candidate，错误选择 `feature`。

`max:40` 与 `under $40` 的既有 upper-bound 行为通过。

### 5.2 修复后定向测试

修复完成后，相关定向测试得到：

```text
6 passed, 60 deselected in 0.06s
```

其中包括 5 个新 regression cases，以及原有 hyphenated catalog-text compatibility case。

### 5.3 修复后全仓库测试

```text
70 passed in 0.28s
```

### 5.4 Diff 检查

```text
git diff --check
```

结果：通过，无 whitespace error。

## 6. 修改范围

只修改以下 4 个文件：

```text
src/policy.py
src/retrieval.py
tests/test_catalog.py
tests/test_state_policy.py
```

Diff 统计：

```text
4 files changed
84 insertions
7 deletions
```

未修改：

- `src/agent.py`；
- shared `src/types.py` / `src/config.py`；
- catalog loader；
- validator；
- evaluator、数据集或公开标签；
- semantic retrieval。

## 7. 当前项目状态

A 与 B 的独立模块及本次 contract 修复均已通过测试，可以进入 D 的正式 assembly 阶段。

当前尚未完成：

```text
src.agent.Agent
-> StateManager / LocalParser
-> QuestionPolicy
-> LexicalRetriever
-> ConstraintRanker
-> validate_recommendations
-> exact Top-10 response
```

在 D 完成上述调用链并通过 e2e test 后，才能运行 official local evaluator 并生成正式 E1/E2 结果。

## 8. Git 提交方式

本次修复应从独立分支提交：

```text
fix/a-b-integration-contracts
```

建议 commit message：

```text
fix: align A/B budget and candidate contracts
```

Push 后创建 PR：

```text
base: main
compare: fix/a-b-integration-contracts
```

PR 应只包含上述 4 个文件。
