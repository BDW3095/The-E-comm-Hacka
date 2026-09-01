# Shopping Copilot：E0 到 E3 技术演进与评测总结

**更新日期：** 2026-09-01  
**评测集：** 官方 public set，200 个 session  
**最终记录版本：** E3，commit `17313bee3f3ec192d5c9b629d81c181fc366b4f8`

> 本文档总结项目从官方弱基线 E0 到当前 E3 的完整演进，包括系统架构、代码改动、集成修复、官方评测结果、失败诊断、消融实验和后续风险。文中的 public evaluator 结果只用于离线分析；生产 Agent 不读取标签、sample ID、scenario type 或 evaluator 输出。

---

## 1. 一页结论

我们从官方未修改的 BM25 starter 出发，先完成 A/B/D 的确定性离线 Agent 集成，再依次修复 Intent Override 的状态继承问题，并加入累计查询覆盖率排序特征。

最终 E3 在同一套 200-session 官方 public evaluator 上达到：

- `Hit Rate@10 = 0.880000`
- `MRR = 0.554861`
- `MTTC = 3.330000`
- `Efficiency = 0.767000`
- `TechnicalScore = 0.759858`

相对 E0：

- TechnicalScore 从 `0.106710` 提升至 `0.759858`，绝对提升 `+0.653148`，约为 E0 的 `7.12 倍`；
- Hit@10 从 `12.5%` 提升至 `88.0%`；
- MTTC 从 `9.81` 轮降至 `3.33` 轮；
- miss 数从约 `175/200` 降至 `24/200`。

E1、E2、E3 每一步都通过了完整仓库测试和官方 evaluator。曾出现但导致分场景回退的排序特征已通过消融实验撤销，没有保留在最终 E3 中。

---

## 2. 评测口径

### 2.1 官方数据

- 固定 catalog：50,000 个商品；
- public set：200 个 session；
- public scenario 构成：
  - Buying：80；
  - Browsing：80；
  - Intent Override：30；
  - Boundary：10；
- private final set：800 个 session，当前不可见。

### 2.2 官方技术分公式

```text
TechnicalScore = 0.50 × HitRate@10 + 0.30 × MRR + 0.20 × Efficiency
Efficiency = clip((11 - MTTC) / 10, 0, 1)
```

指标含义：

| 指标 | 含义 | 系统要做好的事 |
|---|---|---|
| Hit Rate@10 | 目标商品是否出现在 Top-10 | 保证召回覆盖，并输出合法、去重的 10 个商品 |
| MRR | 目标商品第一次出现的位置 | 把正确商品尽量排到第 1–3 名 |
| MTTC | 首次命中目标平均需要多少轮 | 尽早推荐，不进行无效追问 |
| Efficiency | MTTC 映射后的效率得分 | 用更少对话轮数完成转化 |

官方没有公布“TechnicalScore 多少算合格”的硬阈值。因此本文将 E0 作为可复现基线，通过同一环境下的增量对比和分场景无回退决定是否保留改动。

### 2.3 评测纪律

- 所有 E0–E3 运行均使用官方 local evaluator；
- E1–E3 全部为 offline deterministic 路径，没有网络或在线模型调用；
- evaluator 报告的 token usage 为 0；
- 原始结果保存在本地 `artifacts/`，该目录被 Git 忽略；
- production Agent 不读取 public labels、目标商品、sample ID、scenario type 或离线结果文件；
- 每项排序调整都同时检查 overall 和四类 scenario，不能只看总分。

---

## 3. E0–E3 总体结果

| 版本 | Hit@10 | MRR | MTTC | Efficiency | TechnicalScore | 相对上一版 |
|---|---:|---:|---:|---:|---:|---:|
| E0 | 0.125000 | 0.068034 | 9.810000 | 0.119000 | **0.106710** | 基线 |
| E1 | 0.805000 | 0.501044 | 3.945000 | 0.705500 | **0.693913** | **+0.587203** |
| E2 | 0.840000 | 0.510145 | 3.685000 | 0.731500 | **0.719343** | **+0.025430** |
| E3 | 0.880000 | 0.554861 | 3.330000 | 0.767000 | **0.759858** | **+0.040515** |

### 3.1 失败数量与首位命中

| 版本 | Miss 数 | Rank-1 命中 | 说明 |
|---|---:|---:|---|
| E0 | 约 175 | 未单独记录 | 只有 25/200 session 命中 Top-10 |
| E1 | 39 | 78 | 完成 A/B/D 首次正式集成 |
| E2 | 32 | 79 | Intent Override miss 从 20 降至 13 |
| E3 | 24 | 88 | 总 miss 再减少 8，首位命中增加 9 |

### 3.2 分场景最终对比

| Scenario | E0 Hit@10 | E1 Hit@10 | E2 Hit@10 | E3 Hit@10 | E3 MRR | E3 MTTC |
|---|---:|---:|---:|---:|---:|---:|
| Boundary | 0.000000 | 0.900000 | 0.900000 | **1.000000** | 0.743452 | 3.200000 |
| Browsing | 0.025000 | 0.887500 | 0.887500 | **0.937500** | 0.560813 | 2.775000 |
| Buying | 0.237500 | 0.887500 | 0.887500 | **0.925000** | 0.591682 | 2.550000 |
| Intent Override | 0.133333 | 0.333333 | **0.566667** | **0.566667** | 0.377937 | 6.933333 |

E3 的 24 个 miss 分布为：Browsing 5、Buying 6、Intent Override 13、Boundary 0。当前最明显的薄弱点仍是 Intent Override。

---

## 4. E1 之前的模块基础与集成修复

E1 不是从空文件直接产生。正式 assembly 前，A、B、C、D 已分别建立了核心模块和接口。

### 4.1 Engineer A：Catalog、召回与排序

主要文件：

- `src/catalog.py`
- `src/retrieval.py`

主要能力：

1. 从官方 50k catalog 建立本地索引；
2. 使用 SQLite FTS5 做 lexical retrieval；
3. 每轮先召回 Top-200，再做 structured constraint rerank；
4. 将明确的 catalog details 映射到 `category/material/color/size/style/brand/feature` 等属性；
5. color 使用 `positive_evidence_only`：明确命中可加分，不匹配、多色、缺失或只在 description 出现均保持中性；
6. `validate_recommendations()` 过滤非法和重复 ID，并用稳定 fallback 补齐恰好 Top-10；
7. catalog 异常或候选不足时仍保持输出 contract；若 catalog 本身不足以提供 10 个合法唯一 ID，则明确报错。

这里没有采用“非预期商品统一扣分”的策略。原因是 catalog 属性可能缺失或证据不可靠，盲目扣分会把潜在正确商品推走。只有明确、可靠、语义正确的负向约束或预算上限冲突才适合惩罚。

### 4.2 Engineer B：状态、解析与提问策略

主要文件：

- `src/state.py`
- `src/policy.py`

主要能力：

1. 将每轮用户文本解析为 positive/negative slots；
2. 区分 `max`、`min` 和 `target` 三种预算语义；
3. 将同一 session 的有效条件累积为 cumulative query；
4. 隔离不同 session，防止状态串线；
5. 处理 Boundary 中的“无偏好”，避免重复询问；
6. 处理 Intent Override，清除已被用户否定的旧偏好；
7. 只返回官方允许的 `ask_attribute`，第 10 轮停止追问；
8. 使用确定性的 question policy，保证离线可复现。

### 4.3 Engineer D：共享类型与官方入口

主要基础：

- 共享 `Candidate`、`ParsedTurn`、`SessionState`；
- 统一 config；
- 保持官方构造方式 `Agent(args.catalog)`；
- `starter.agent.Agent` 只作为官方入口，实际实现放在 `src.agent.Agent`；
- 输出官方 response schema。

### 4.4 Engineer C：离线结果分析

主要文件：

- `analysis/summarize_results.py`
- 对应测试文件；

作用：

- 读取官方 evaluator 的 JSON 结果；
- 统一汇总 overall、scenario、rank bucket、miss 数和 token usage；
- 对比 E0/E1/E2/E3；
- 只用于离线实验，不被 production Agent import。

### 4.5 A/B contract 修复

在正式 E1 assembly 前，单模块测试虽然通过，但跨模块检查发现两个问题。

#### 问题一：预算语义错误

A 曾把 B 输出的以下三类值都当作最高预算：

```text
max:40
min:25
target:50
```

这会把“至少 25”和“目标约 50”误解成“不超过该价格”，导致错误扣分。修复后只有 `max:40`、`under $40`、`at most $40` 等明确 upper-bound 表达会触发超预算 penalty；`min` 和 `target` 不再被误判。

#### 问题二：policy 无法读取 shared Candidate

共享 `Candidate` 使用 `@dataclass(slots=True)`，没有 `__dict__`。B 的 policy 原先依赖 `candidate.__dict__`，因此读不到真实候选的 `product` 和 `search_text`，Information Gain 会退化为固定 fallback。修复后 policy 直接读取公开字段，并保留 dictionary candidate 兼容。

新增 regression tests 先在旧实现上复现 `3 failed, 2 passed`，修复后相关测试及全仓测试全部通过。这一步说明“各模块独立通过”不等于“跨模块 contract 正确”。

---

## 5. E0：官方弱 BM25 基线

### 5.1 版本定义

- source commit：`27730cec9cfa0a8b07076ebdf4dd388c1a6ef724`
- tag：`e0-baseline`
- 代码状态：经校验的官方 participant kit 中未修改的 `starter/agent.py`
- 运行命令：`python3 -m evaluator.local_evaluator`

### 5.2 结果

| Metric | E0 |
|---|---:|
| Sample count | 200 |
| Hit Rate@10 | 0.125000 |
| MRR | 0.068034 |
| MTTC | 9.810000 |
| Efficiency | 0.119000 |
| TechnicalScore | **0.106710** |

分场景：

| Scenario | Hit@10 | MRR | MTTC |
|---|---:|---:|---:|
| Boundary | 0.000000 | 0.000000 | 11.000000 |
| Browsing | 0.025000 | 0.004514 | 10.750000 |
| Buying | 0.237500 | 0.126508 | 8.625000 |
| Intent Override | 0.133333 | 0.104167 | 10.066667 |

### 5.3 E0 说明了什么

E0 的价值主要是验证官方数据、环境、入口和 evaluator 可复现，而不是代表团队方案的水平。它基本没有完整利用多轮状态、结构化约束、有效提问和稳定 rerank，因此召回率和对话效率都较低。

---

## 6. E0 → E1：首次完整离线 Agent 集成

### 6.1 版本定义

- source commit：`a3636cff5564bb1513bcaa5b9561c07c12a94fa6`
- 主要 commit：`feat: assemble deterministic E1 agent pipeline`
- 修改：`src/agent.py`、`tests/test_agent_e2e.py`

### 6.2 E1 调用链

```text
user message
  ↓
B: StateManager / LocalParser 更新多轮状态
  ↓
A: LexicalRetriever 从 50k catalog 召回 Top-200
  ↓
A: ConstraintRanker 按累计约束重排
  ↓
B: QuestionPolicy 选择下一条合法问题
  ↓
D: validate_recommendations + 官方 response assembly
  ↓
恰好 10 个合法、唯一 parent_asin
```

### 6.3 具体改动

1. `src.agent.Agent` 正式串联 A、B 模块，不再只是 scaffold；
2. 构造时在 catalog 可用的情况下建立 `CatalogIndex`；
3. 每轮先更新 session state，再使用 cumulative query 搜索；
4. lexical route 返回 Top-200，随后按正向、负向、预算等 structured constraints 重排；
5. question policy 根据当前状态和候选决定 `ask_attribute`；
6. validator 保证 recommendations 恰好为 Top-10、合法且不重复；
7. 增加测试环境下的 missing-catalog degradation，避免纯 contract test 必须加载完整 50k 数据；
8. 响应始终包含 `message`、`ask_attribute`、`recommendations` 和 `usage`；
9. 新增完整 Top-10 与跨轮条件累积的 e2e tests。

### 6.4 测试和结果

- repository tests：`79 passed`
- public evaluator runtime：约 52 秒
- 网络/模型调用：无

| Metric | E0 | E1 | Delta |
|---|---:|---:|---:|
| Hit@10 | 0.125000 | 0.805000 | +0.680000 |
| MRR | 0.068034 | 0.501044 | +0.433010 |
| MTTC | 9.810000 | 3.945000 | -5.865000 |
| Efficiency | 0.119000 | 0.705500 | +0.586500 |
| TechnicalScore | **0.106710** | **0.693913** | **+0.587203** |

E1 是最大的一次跃升，证明“多轮状态 + FTS5 Top-200 + structured rerank + 合法问题策略 + 输出校验”的完整系统远强于官方 weak baseline。

### 6.5 E1 失败诊断

E1 共 39 个 miss，其中 20 个来自 Intent Override。对这 20 个失败逐项检查发现：

- 19 个目标商品在 override 当轮甚至没有进入 lexical Top-200；
- 另 1 个目标位于第 158 名，未进入最终 Top-10；
- override reset 在清除旧偏好的同时，把用户仍在寻找的产品 category 也清除了；
- 结果是累计查询可能只剩 `cotton`、`leather`、`polyester` 等非常宽泛的材料词，召回方向丢失。

离线 counterfactual 分析显示，恢复合理 category 至少可救回 7/20 个 override miss，因此 E2 聚焦该问题。

---

## 7. E1 → E2：修复 Intent Override 的 category 继承

### 7.1 版本定义

- final source commit：`e3fa2c64513a6be9d7927397143cb912246783fc`
- 主要修复 commit：`8076aaa fix: preserve category across preference overrides`
- 消融撤回 commit：`e3fa2c6 revert: drop regressive category token bonus`

### 7.2 状态修复

新的 override 行为：

1. 如果用户只是覆盖材质、颜色、风格等 preference，而没有说新的产品类型，则保留已有 product category；
2. 如果 override 明确提出新的 positive 或 negative category，则使用新 category，不保留旧 category；
3. 被覆盖的旧 preference 仍会清除；
4. question history、no-preference 和 exhaustion 等 override 相关状态仍按既有规则重置。

示例：

```text
旧意图：black shirt
新消息：Actually, ignore black. I need cotton.
结果：保留 shirt，删除 black，加入 cotton
```

而下面这种情况不会错误保留旧 category：

```text
旧意图：shirt
新消息：Actually I need leather boots.
结果：category 改为 boots，不再保留 shirt
```

### 7.3 Parser 修复

optional-article regex 曾把 `accessories` 开头的字符错误匹配成冠词 `a`，导致解析结果变成 `ccessories`。E2 修复了该正则边界，并补充 regression test。

### 7.4 被撤回的 category token bonus

第一版 E2 候选同时加入了 broad category token-overlap ranking bonus，TechnicalScore 达到 `0.717105`，但 Browsing MRR 从 E1 的 `0.536419` 降到 `0.514350`。

这个结果说明：

- overall 分数上涨不代表所有用户场景都更好；
- 对宽泛 category token 统一加分会过度提升表面词匹配商品；
- 它可能把原本排得更高的正确商品挤到后面。

因此 commit `e3fa2c6` 撤销该全局 bonus。最终 E2 只保留高置信度的状态和 parser 修复。

### 7.5 测试和结果

- repository tests：`80 passed`
- runtime：约 53 秒
- 非 Override 的 Buying、Browsing、Boundary 指标与 E1 完全一致，无回退

| Metric | E1 | E2 | Delta |
|---|---:|---:|---:|
| Hit@10 | 0.805000 | 0.840000 | +0.035000 |
| MRR | 0.501044 | 0.510145 | +0.009101 |
| MTTC | 3.945000 | 3.685000 | -0.260000 |
| Efficiency | 0.705500 | 0.731500 | +0.026000 |
| TechnicalScore | **0.693913** | **0.719343** | **+0.025430** |

Intent Override：

| Metric | E1 | E2 |
|---|---:|---:|
| Hit@10 | 0.333333 | 0.566667 |
| MRR | 0.283333 | 0.344008 |
| MTTC | 8.666667 | 6.933333 |
| Miss 数 | 20 | 13 |

E2 将总 miss 从 39 降到 32，且没有牺牲其他三个场景，因此被保留。

---

## 8. E2 → E3：累计查询覆盖率重排

### 8.1 版本定义

- final source commit：`17313bee3f3ec192d5c9b629d81c181fc366b4f8`
- 初始实现：`cd3260a feat: reward cumulative query coverage in reranking`
- 最终权重：`17313be tune: strengthen cumulative query coverage bonus`
- 修改：`src/retrieval.py`、`tests/test_catalog.py`

### 8.2 E2 剩余失败诊断

E2 的 32 个 miss 中：

- 28 个属于 ranking failure：目标已在 Top-200，但最终排名在第 10 名之后；
- 4 个属于 recall failure：目标不在 Top-200，且全部来自 Intent Override。

28 个 ranking failure 的位置：

- rank 11–20：11 个；
- rank 21–50：9 个；
- rank 51–100：6 个；
- rank 101–200：2 个。

这说明 E2 的主要矛盾已从“召回不到”转为“召回到了但排序不够好”。原 ranker 对每类 structured attribute 基本只记录是否命中，无法充分区别：

- 只匹配累计需求中的一个词；
- 同时覆盖 category、material、style、use case 等多个用户词。

### 8.3 Query coverage 特征

E3 从 `state.last_query` 提取去重后的累计查询 token，并检查候选的 catalog `search_text` 覆盖了多少 token：

```text
coverage = |query_tokens ∩ candidate_tokens| / |query_tokens|
coverage_bonus = 20.0 × coverage
```

效果：

- 完整覆盖累计需求的候选得到更高 bonus；
- 只匹配一个宽泛词的候选加分较少；
- 该特征只使用当前用户表达和 catalog 文本；
- 不使用 public target、session 标签或 evaluator 结果；
- 原有 positive/negative attribute、budget 和 color 规则保持不变。

新增 generic regression test，验证“覆盖更多累计 query token 的候选”可以超过只覆盖少量 token 的候选。

### 8.4 权重消融

| Coverage weight | Hit@10 | MRR | MTTC | TechnicalScore | 决策 |
|---:|---:|---:|---:|---:|---|
| 12.0 | 0.880000 | 0.548264 | 3.335000 | 0.757779 | 有效，但非最终 |
| 20.0 | 0.880000 | 0.554861 | 3.330000 | **0.759858** | 保留 |

权重 20 相比 12：

- Hit@10 不下降；
- overall MRR 更高；
- 四类 scenario 的 MRR 均更好；
- 因此选择 20，而不是仅按单个样本调整。

### 8.5 未采用 strict AND FTS route

团队还检查了“所有查询 token 必须同时出现”的 strict FTS route。对 E3 剩余 24 个 miss 分析后，只有 4 个目标进入该 route 的 Top-10；与此同时，许多现有正确结果位于 E3 的第 6–10 名，新 route 融合可能把这些边缘命中挤出 Top-10。

由于潜在收益窄、替换风险高，且没有足够证据证明无回退，该 route 没有加入 E3。

### 8.6 测试和结果

- repository tests：`81 passed`
- runtime：约 61 秒
- 网络/模型调用：无

| Metric | E2 | E3 | Delta |
|---|---:|---:|---:|
| Hit@10 | 0.840000 | 0.880000 | +0.040000 |
| MRR | 0.510145 | 0.554861 | +0.044716 |
| MTTC | 3.685000 | 3.330000 | -0.355000 |
| Efficiency | 0.731500 | 0.767000 | +0.035500 |
| TechnicalScore | **0.719343** | **0.759858** | **+0.040515** |

E3 相对 E2 的四类 scenario 均提升或持平：

- Boundary Hit@10：`0.90 → 1.00`；
- Browsing Hit@10：`0.8875 → 0.9375`；
- Buying Hit@10：`0.8875 → 0.9250`；
- Intent Override Hit@10 保持 `0.566667`，MRR 从 `0.344008` 提升到 `0.377937`。

---

## 9. 关键实验决策汇总

| 改动 | 实验结果 | 最终状态 | 原因 |
|---|---|---|---|
| A/B budget contract 修复 | 消除 `min/target` 被当作 max 的错误 | 保留 | 语义和接口修复，有 regression test |
| shared Candidate 读取修复 | Information Gain 可读取 slots dataclass | 保留 | 修复真实集成路径 |
| A/B/D 完整确定性 pipeline | Score `0.106710 → 0.693913` | 保留 | 核心系统成立 |
| Override 保留 category | Override miss `20 → 13` | 保留 | 只在未出现新 category 时保留，边界明确 |
| `accessories` parser 修复 | 防止解析为 `ccessories` | 保留 | 明确 parser bug |
| broad category token bonus | 总分有提升，但 Browsing MRR 回退 | **撤回** | 影响过宽，不满足无回退原则 |
| query coverage，weight 12 | Score `0.757779` | 被 weight 20 替代 | 有效但 MRR 低于 weight 20 |
| query coverage，weight 20 | Score `0.759858` | 保留 | Hit 稳定，overall 和分场景 MRR 更好 |
| strict all-token FTS route | 24 个 miss 中仅 4 个进入其 Top-10 | 不采用 | 收益有限，可能挤掉现有 rank 6–10 命中 |

---

## 10. 测试与复现

### 10.1 仓库测试增长

| 阶段 | 全仓结果 | 新增验证重点 |
|---|---:|---|
| A/B contract 修复后 | 70 passed | budget 语义、slots Candidate |
| E1 | 79 passed | Agent assembly、Top-10、跨轮累积 |
| E2 | 80 passed | override category、parser 边界 |
| E3 | 81 passed | cumulative query coverage rerank |

运行完整测试：

```powershell
python -m pytest -q
```

### 10.2 运行 E3 官方 evaluator

在已按 README 放置官方 `data/` 和 `evaluator/` 的仓库根目录运行：

```powershell
python -m evaluator.local_evaluator --output artifacts/e3_weight20_results.json
```

### 10.3 生成 E0–E3 对比报告

```powershell
python analysis/summarize_results.py `
  E0=docs/official_reference/baseline_results.json `
  E1=artifacts/e1_results.json `
  E2=artifacts/e2_final_results.json `
  E3=artifacts/e3_weight20_results.json `
  --output artifacts/e0_e1_e2_e3_summary.md
```

`analysis/summarize_results.py` 会验证结果字段并生成 deterministic Markdown。若需要本地定位失败，可临时使用 `--include-failure-ids`，但包含 public sample IDs 的输出不应提交到 production repo。

---

## 11. 当前 E3 的系统能力

E3 已具备：

- 50k catalog 的离线 SQLite FTS5 检索；
- Top-200 召回与结构化约束重排；
- 多轮 positive/negative preference 累积；
- max/min/target 预算语义区分；
- Buying、Browsing、Boundary、Intent Override 状态处理；
- 合法且不会重复追问的 question policy；
- override 时的条件替换和 category 继承；
- cumulative query coverage bonus；
- 非法、重复、缺失候选清理与稳定 Top-10 fallback；
- 官方 `starter.agent.Agent` 入口；
- 无网络、无 LLM、无 token 消耗的确定性运行；
- 离线 evaluator 结果比较与失败诊断脚本。

---

## 12. 当前剩余问题与风险

### 12.1 Intent Override 仍是主要短板

E3 仍有 13 个 Intent Override miss，占全部 24 个 miss 的一半以上。E2 修复解决了 category 被错误清除的问题，但仍存在：

- override 后 query 过短或表达过于宽泛；
- 部分目标不在 lexical Top-200，属于召回问题；
- 部分目标已召回但仍未进入 Top-10，属于排序问题。

### 12.2 仍有 recall 与 ranking 两类问题

后续优化必须先区分：

- **Recall failure：** 目标不在 Top-200，继续调当前 reranker 没有用；
- **Ranking failure：** 目标已在 Top-200，可以通过更精细特征改善排序。

不能用同一个“统一扣分/统一加分”同时解决两类问题，否则容易造成已有场景回退。

### 12.3 Public set 过拟合风险

E2/E3 的每项改动都来自通用错误模式，并且 production code 不读取标签，但反复查看同一 200-session public set 仍可能带来选择偏差。最终 private 800 sessions 才能验证泛化。

### 12.4 运行与提交限制仍需最终确认

提交前仍需确认：

- 最终 runtime 限制；
- network policy；
- derived SQLite index 是否允许随包提交；
- package size；
- optional model weights 的规则。

当前 E3 不依赖外部模型，因此比需要在线 API 或大型权重的方案风险更低。

### 12.5 可考虑但尚未实现的 E4 方向

1. 对 coverage token 加入 specificity/IDF，降低常见词权重；
2. 为 recall failure 增加高精度 secondary lexical route，并用 RRF 融合；
3. 针对 override 后极短 query 做高精度 query rewrite；
4. 每一项都必须做 overall + scenario + rank-distribution 消融，出现 Buying/Browsing/Boundary 回退则撤销。

这些是后续候选，不属于当前 E3 已完成内容。

---

## 13. 最终结论

E0 到 E3 的演进不是简单地“不断加功能”，而是按以下闭环推进：

```text
建立官方可复现基线
→ 集成完整离线 Agent
→ 按 scenario 和 miss 类型定位问题
→ 做最小范围修复
→ 运行完整测试和官方 evaluator
→ 保留无回退增益，撤销有回退实验
```

E1 证明完整架构有效；E2 修复 Intent Override 的状态语义；E3 改善已召回候选的排序。最终 `TechnicalScore = 0.759858`，四类场景相对 E2 均提升或持平，当前版本可作为稳定的 E3 checkpoint 和后续演示、报告及 E4 实验基线。

