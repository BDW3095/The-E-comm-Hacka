# Muse Shopping Copilot：4 天实施计划、四人分工与 Coding Agent 指南

> 目标：在 4 天内交付一个可由官方 evaluator 直接评分、可在断网环境运行的 offline-first Python Agent。系统每轮都输出有效 Top-10 parent_asin，并以 Hit Rate@10、MRR 与 Efficiency 为唯一优化依据。
>
> 本文沿用旧 four_day_implementation_plan.md 的结构，但仅采用当前确认的比赛策略：MVP only、严格 Override、other-until-exhausted 和可关闭的 Dense Retrieval。

---

## 1. 产品 workflow：四个人如何拼成一个可评分产品

### 1.1 用户视角的完整流程

~~~mermaid
flowchart TD
    R["Evaluator calls reset(session_id, user_profile)"] --> D0["D: create SessionState"]
    U["Current user_message"] --> B1["B: parse slots, Boundary and Override"]
    D0 --> B1
    B1 --> G{"Strong Override?"}
    G -->|yes| B2["B: reset current intent state"]
    G -->|no| B3["B: merge current intent state"]
    B2 --> Q["B: build cumulative query"]
    B3 --> Q
    Q --> A1["A: FTS5 BM25 lexical Top-200"]
    Q --> C1["C: optional dense Top-200"]
    A1 --> C2["C: RRF fusion when enabled"]
    C1 --> C2
    A1 --> A2["A: unified constraint rerank"]
    C2 --> A2
    A2 --> D1["D: validate unique catalog-valid Top-10"]
    B1 --> B4["B: choose ask_attribute"]
    D1 --> O["Official response"]
    B4 --> O
    O --> C3["C: offline results analysis"]
~~~

A 负责让正确商品进入候选池；B 负责理解并记住用户意图；C 负责以数据验证每一次变化和可选语义检索；D 负责把这些能力组装成官方 evaluator 真正能调用、能提交的 Agent。

### 1.2 架构 review：四人架构是否缺人或缺模块

四人架构足够，不需要第五位 technician。但原架构有三个易被遗漏的责任，本计划已明确 ownership：

| 容易遗漏的部分 | Owner | 解决办法 |
|---|---|---|
| 策略可切换性 | B 定义，D 固化 | 通过 QuestionPolicyConfig 在 simulator_optimized 和 information_gain 间切换。 |
| 分数与失败根因 | C 分析，D 记录 | Agent 不写 persistent Trace；C 在 evaluator 后分析 results.json，D 维护 experiment_log.md。 |
| 未公开 evaluator / runtime 规则 | PM/D 询问，D 固化 | 问题集中在 docs/organizer_engineer_qa.md；答复只通过 config 和 feature flag 改变策略。 |
| shared contract 与合并 | D | D 唯一维护 shared types、config 和官方入口，其他人通过 PR 提议变更。 |

### 1.3 交付优先级：必须完成与必须关闭的能力

| Priority | 能力 | 本次是否实现 | 通过条件 |
|---:|---|---:|---|
| P0 | 官方 Agent interface、catalog-valid Top-10、SessionState、SQLite FTS5 | 必须 | 能完成官方 evaluator |
| P1 | cumulative query、negative constraints、严格 Override、other-until-exhausted、metadata ranking | 必须 | E2 总分高于 0.10671 baseline |
| P2 | BAAI/bge-small-en-v1.5、Dense Top-200、RRF | 仅 Day 3 实验 | 总分严格高于 E2，且关闭后 P0/P1 不受影响 |
| P3 | reranker、外部 LLM API、fine-tuning、Provider、persistent Trace | 不做 | 仅作为赛后 future work |

BM25 是以词面匹配做检索的算法；FTS5 是 SQLite 内置的全文索引。RRF 是按名次合并 lexical 和 dense 两条检索路线的方法，不直接相加两者原始分数。

---

## 2. 共享设计：写代码前必须冻结的 contract

### 2.1 推荐目录、文件 ownership 与禁止修改区域

~~~
data/                              # 官方 catalog 与 public sessions；只读
evaluator/                         # 官方 evaluator；只读
starter/
  agent.py                         # D：唯一官方入口，只 re-export src.agent.Agent
src/
  __init__.py                      # D
  types.py                         # D：共享数据结构和常量
  config.py                        # D：策略配置与 feature flags
  catalog.py                       # A：catalog normalization 与 FTS5 index
  retrieval.py                     # A：lexical retrieval、constraint rerank、validation
  state.py                         # B：parser、state、Override、query builder
  policy.py                        # B：QuestionPolicy 与英文 message template
  semantic.py                      # C：仅 P2，DenseRetriever 与 RRF
  agent.py                         # D：官方 interface、组装和 fallback
analysis/
  summarize_results.py             # C：只读 results.json 的离线分析
tests/
  test_catalog.py                  # A
  test_state_policy.py             # B
  test_analysis.py                 # C
  test_semantic.py                 # C，仅 P2
  test_agent_e2e.py                # D
docs/
  experiment_log.md                # D：实验记录
  organizer_engineer_qa.md         # PM/D：主办方问题、答复后的决策表
  new_four_day_implementation_plan.md
~~~

不得修改 evaluator、catalog、public_set、public label 或官方评分配置。不得创建 llm_client.py、providers.py 或 Agent runtime trace.py。

### 2.2 环境 preflight：Day 1 必须先通过的四项检查

在任何 feature branch 开始前，D 必须完成并记录以下检查。它们不属于实现功能，但任一项失败都会使后续 4 天的结果不可信。

1. 从官方 participant kit 解压 data、evaluator、starter 与 docs；确认 catalog 与 public set 位于官方相对路径。
2. 使用 SHA256SUMS 校验下载的 catalog 压缩包，再解压；不从上游 Amazon dataset 重建或替换 catalog。
3. 运行官方 baseline：python -m evaluator.local_evaluator，确认输出 0.10671；保留该结果为 E0，不在改写 starter 后重新称其为 baseline。
4. 执行最小 SQLite FTS5 探测：成功创建内存 FTS5 virtual table。官方 starter 依赖 FTS5；若环境不支持，应当天停止并解决环境，而不是临时换掉 retrieval 技术。

### 2.3 src/types.py 与 src/config.py：团队的共同语言

Day 1 上午由 D 创建；Day 3 前字段名不得自行更改。

~~~
Candidate:
  parent_asin: str
  score: float                 # 内部排序；越大越相关
  search_text: str             # 商品可检索文本的安全拼接
  product: dict                # 原 catalog record，只读
  route_ranks: dict[str, int]  # 例如 {"lexical": 4, "dense": 9}

ParsedTurn:
  positive_slots: dict[str, list[str]]
  negative_slots: dict[str, list[str]]
  normalized_query: str | None
  is_override: bool

SessionState:
  session_id: str
  profile_tags: list[str]
  messages: list[str]
  positive_slots: dict[str, list[str]]
  negative_slots: dict[str, list[str]]
  asked_specific_attributes: set[str]
  no_preference_attributes: set[str]
  other_exhausted: bool
  intent_epoch: int
  turn: int
  last_query: str
  mode: str                    # buying 或 browsing

QuestionPolicyConfig:
  mode: str                    # simulator_optimized 或 information_gain
  final_turn: int              # 10
  askable_attributes: tuple[str, ...]

RankingConfig:
  color_conflict_mode: str     # 默认 positive_evidence_only；parent product 不做 color penalty
  positive_bonus: float        # 默认 2.0
  negative_penalty: float      # 默认 6.0
  color_bonus: float           # 默认 1.5
  budget_penalty: float        # 默认 0.5
  budget_tolerance: float      # 默认 1.15
  query_coverage_enabled: bool # 默认 True
  query_coverage_weight: float # 默认 20.0
~~~

解释：

- slot 是一项结构化偏好，例如 material=["cotton"]。
- positive_slots 是用户想要的条件；negative_slots 是排除条件，例如 not leather。
- intent_epoch 表示第几次意图。用户明确替换需求时加一。
- mode 默认 simulator_optimized。未来 private simulator 若改变 other 行为，只改 config，不改 Agent 主链路。
- color_conflict_mode 默认 positive_evidence_only：明确命中用户所需 color 才加分；其他颜色、多色、缺失或不可靠 color 一律中性。已确认 parent_asin 是可能包含多个 SKU variant 的 parent product，所以任何 non-match color 都不是负向证据，不做 penalty 或 hard filter。
- E4 V4 将所有当前 ranking constants 冻结在 RankingConfig 中；default values 是已验证的 lexical baseline，不得在 release 阶段调参。
- 主办方待确认问题与每种答复的配置动作见 docs/organizer_engineer_qa.md。未得到答复不能阻塞 P0/P1；P2 的提交须同时满足实验 gate 与运行/提交边界。

规则：

- Slot key 固定为 category、material、color、size、style、brand、budget、feature、use_case。
- category 和 brand 可以用于 retrieval ranking，但不进入主动提问候选。
- 所有 shared object 都不得包含 ground_truth、sample_id 或 scenario label。

### 2.4 模块调用顺序与官方 interface

官方 evaluator 会 import starter.agent.Agent 并构造 Agent(catalog_path)。starter/agent.py 必须只 re-export：

~~~python
from src.agent import Agent
~~~

每轮固定调用顺序如下。任何 optional module 失败都只能回退，不能抛 exception：

~~~
1. Agent.reset / StateManager.get_state
2. LocalParser.parse(user_message)
3. StateManager.update_or_reset(parsed_turn)
4. QueryBuilder.build(state)
5. LexicalRetriever.retrieve(query, limit=200)
6. optional DenseRetriever.retrieve(query, limit=200)
7. optional RRF fusion
8. ConstraintRanker.rerank(unified candidates, state)
9. RecommendationValidator.take_valid_unique_top10(...)
10. QuestionPolicy.choose(state, candidates, turn)
11. return official response dict
~~~

没有 P2 时，A 的 lexical Top-200 直接进入 unified constraint rerank。启用 P2 时顺序必须是：

~~~
Lexical Top-200 + Dense Top-200 → RRF → unified constraint rerank → Top-10
~~~

---

## 3. 四位成员的可执行说明

### A — Data & Lexical Retrieval Engineer

#### 1) 这个人做什么、在链路中的作用和最终结果

A 负责图中的 catalog → FTS5 BM25 → unified constraint rerank。候选池的覆盖由 A 决定：目标商品若不在候选池，B 的多轮策略和 C 的语义模型都无法把它变成 Top-10。

最终结果是一个确定性的本地 CatalogIndex。给定相同 query 和 SessionState，它从 50k catalog 返回最多 200 个合法 Candidate，并按用户明确条件重新排序。在无网络、无 GPU、price 为空或 metadata 缺失时仍能运行。

#### 2) 要创建哪些 file，每个 file 要包含什么

**src/catalog.py**

catalog.py 把原始 JSONL catalog 变为内存可搜索结构。JSONL 表示每一行都是一件商品的 JSON record，不是一个完整 JSON array。

- 实现 flatten_text(value) -> str：None 变空字符串；list 合并非空元素；dict 变为 key value 文本。这样空字段不会导致 crash。
- 定义 ProductDocument，保存 parent_asin、search_text、category_path、规范化 attributes、price、quality_prior 和原始 product。
- 实现 extract_attributes(product)：从 title、features、details、categories、store 中抽取 material、color、size、style、brand、use_case 和 price。
- normalization 统一表达方式，例如 grey 变 gray、所有比较词变小写，保证 black 与 Black 可匹配。
- 实现 CatalogIndex(catalog_path)：流式读取 catalog，建立 parent_asin → ProductDocument mapping、有效 ID set 和 SQLite FTS5 table。
- 提供 get_product(parent_asin) 和 all_documents()。all_documents() 只供 C 在 P2 编码商品文本使用。

**src/retrieval.py**

retrieval 是从 50k 商品缩小到候选集的过程；它只能读取 state，不能修改 state。

- 实现 compile_positive_query(query)：保留字母数字的正向 token，去 stopwords、去重、最多 40 个词，并安全构造 FTS OR expression。
- negative token 永远不进入 FTS query；否则 not leather 会错误提升 leather 商品。
- 实现 LexicalRetriever.retrieve(query, limit=200) -> list[Candidate]。SQLite bm25 原始数值越小越相关，因此必须转换为 lexical_score = -raw_bm25_score，之后全项目都遵守“越大越相关”。
- 实现 ConstraintRanker.rerank(candidates, state)。category、material、color、brand、size/style、feature/use_case 匹配加分；negative conflict 大幅扣分；已知 price 超预算小幅扣分；price=None 不扣分也不删除。color 使用 positive-evidence-only：可靠 black 加分；其他颜色、多色、缺失、不可靠或仅 description 命中的 color 保持中性。parent_asin 是可能包含多个 SKU variant 的 parent product，因此任何 non-match color 都不是负向证据，不做 penalty 或 hard filter。
- 实现 validate_recommendations(candidates, valid_ids, top_k=10)：去重、移除 catalog 外 ID、按 score desc 和 parent_asin asc 稳定排序。若 reranked candidates 少于 10 个，使用稳定 catalog fallback 补齐未出现的合法 ID；50k catalog 存在时每轮必须恰好输出 10 个 ID。
- FTS 异常或空 query 时同样从稳定 catalog fallback 生成 10 个合法 ID，保证 Agent 每轮仍可评分。

**tests/test_catalog.py**

使用 temporary 小 JSONL fixture，不使用 public labels。覆盖：

- 空 title、空 features、空 details、null price、重复 ID。
- 未知 query 和 FTS 安全 query。
- BM25 分数方向、negative material、稳定排序。
- color 正向匹配与中性行为：black 命中时加分；仅含 red/white 等其他颜色、多色、缺失 color 或仅 description 出现颜色词时不扣分、不被过滤。
- 候选不足、空 query 或 retriever exception 时，仍恰好得到 10 个合法且去重 ID。

#### 3) 如何与其他 technician interact、写文件时注意什么

- A 消费 B 的 last_query、positive_slots 和 negative_slots；只读取，绝不在 retrieval 中修改 state。
- A 向 D 提供 Candidate 和 validation helper，向 C 提供 ProductDocument.search_text；C 不得复制第二套 catalog loader。
- A 必须安全忽略未知 slot，避免 B 将来扩展词典后 retrieval crash。
- A 不读取 public_set 的答案、不改 evaluator、不写 scenario-specific hardcode。
- src/types.py 和 src/config.py 只由 D 修改；若 contract 变化，A 先同步 main 再继续工作。

#### 4) 如何与自己的 Coding Agent 沟通

把本计划、第 2.2 节 shared types、官方 starter agent 和 catalog schema 发给 Coding Agent。先要求它列出 exported function、I/O 与 tests，再允许写代码。

~~~text
You are Engineer A for an offline conversational shopping Agent. Implement only
src/catalog.py, src/retrieval.py, and tests/test_catalog.py. Read but do not
modify types/config/state/policy/agent, evaluator, data, or public labels.

Build a deterministic in-memory CatalogIndex and SQLite FTS5 lexical retriever.
Safely normalize nullable, list, and dict fields. Return Top-200 Candidate
objects with score-higher-is-better semantics, then apply state-driven constraint
reranking. Never put negative tokens into the FTS query. Null price must preserve
eligibility. Use isolated pytest fixtures only; never use network, models, hidden
labels, or sample IDs. Report changed files, exported APIs, test command, and
test result.
~~~

### B — Conversation State & Simulator-Aware Policy Engineer

#### 1) 这个人做什么、在链路中的作用和最终结果

B 负责 user_message → parse → SessionState → query / ask_attribute。官方 respond 每轮只收到最新一句消息，多轮条件不会自动保存；B 决定系统是否记住 cotton、排除 leather、识别真正改意图，并取得下一轮最有价值的信息。

最终结果是一个独立可重置的 StateManager 和 QuestionPolicy。它能累积同一意图条件，避免把普通补充误判为 Override；在当前比赛配置中持续请求 other，直到真正没有额外偏好；每轮都向 A 提供干净 query。

#### 2) 要创建哪些 file，每个 file 要包含什么

**src/state.py**

- 定义 LocalParser.parse(message) -> ParsedTurn。用 deterministic regex 和受控 dictionaries 识别 color、material、budget、size、style、brand、feature、use_case 与 negative condition。deterministic 表示同输入永远得到同输出，不依赖随机 LLM。
- 在负向解析前识别 Boundary：I don't have a preference for X 和 I don't have an additional preference for X。这两类句子表示“不提供条件”，不能错误写入 negative_slots。
- 定义 is_strong_override(message, parsed, state)。实现为两个明确分支：(a) ignore my earlier/previous preference、forget what I said、start over 等显式撤销短语，直接 reset；(b) instead、rather than、change from、switch from 等替换短语，且本轮具有非空 normalized_query 或新 slot 时 reset。不能只匹配单个单词 change、switch 或 rather。
- actually 单独出现永远不是 reset 信号；actually 加一个普通新 slot 也只合并。例如 Actually, I also want blue 必须保留旧 cotton。公开 evaluator 的 Override 句含 ignore my earlier preference，因此仍会被第一分支稳定识别。
- 实现 StateManager.reset(session_id, profile)、update(session_id, message, turn)、build_query(state)。
- Override 时清空当前意图的 positive/negative preference slots、asked_specific_attributes、no_preference_attributes 与 other_exhausted；若 replacement turn 没有给出新的 category，则保留当前 product family category。`instead of`、`rather than`、`change from ... to`、`switch from ... to` 的旧侧 value 不得重新写入新 intent；随后合并新侧 slots 并增加 intent_epoch。
- build_query 只使用当前意图有效正向条件和商品类型。profile tags 仅交给 A 作极弱 tie-break，profile summary 不进入 query。

**src/policy.py**

ask_attribute 是 evaluator 消费的结构化字段；message 只是给 demo 看的英文问句。

- 定义 QuestionPolicy(config)，所有策略必须从 QuestionPolicyConfig 读取，不能分散在 Agent 的 if/else。
- simulator_optimized 是默认 mode：Turn 1–9，只要 other_exhausted=False，就返回 other。公开 simulator 每次 other 最多返回两条未披露条件，所以允许重复。
- 只有收到 I don't have an additional preference for other 才令 other_exhausted=True。
- Boundary 首次 I don't have a preference for other 不代表 exhausted，下一轮仍请求 other。
- information_gain 是备用 mode：或 other exhausted 后，从 material、color、size、style、feature、use_case、budget 中挑一个尚未问过且不在 no_preference set 的字段；可按候选属性覆盖度决定优先级。
- category、brand 永远不进入主动提问候选。
- Turn 10 返回 None；Turn 1–9 必须返回非空且 allowed attribute。
- 实现 render_message(attribute)，为每种字段给出简短、自然的英文 template。

**tests/test_state_policy.py**

覆盖：

- session 隔离、cumulative query、negative condition。
- 普通 `actually` 合并；显式撤销、`instead`、`rather than` 的强 Override reset；孤立 `change`/`rather` 不 reset。replacement statement 的旧侧 size、budget、lexical feature 与 raw feature 必须被丢弃，新侧 value 仍须正常解析。
- 使用 released template 验证 Boundary：首次 no preference for other 后仍请求 other；只有 no additional preference for other 才 exhausted；Turn 10 为 None。
- category 与 brand 永不被选择。
- simulator_optimized 与 information_gain 两种 config mode。
- 所有返回值都在官方 allowed attributes 内。

#### 3) 如何与其他 technician interact、写文件时注意什么

- B 向 A 提供标准化小写 slots 与 last_query；budget 使用结构化 min/max，不能留下任意自然语言。
- B 向 D 提供 ask_attribute 和 message template；D 只封装官方 schema，不重复实现 policy。
- B 可以读取 A 返回的 Candidate list 计算 information_gain，但不能扫描 catalog 或建立 index。
- C 使用 B 的 last_query 生成 dense query；B 若改变 query 格式必须通知 C。
- B 只看 message、state 和 config，不得读取 sample_id、scenario label 或 target。

#### 4) 如何与自己的 Coding Agent 沟通

Coding Agent 必须阅读 evaluator 的 customer_reply 和 Override 逻辑。要求它给每个状态迁移写 regression test，不只测 happy path。

~~~text
You are Engineer B. Implement only src/state.py, src/policy.py, and
tests/test_state_policy.py. Do not modify shared types/config, retrieval,
semantic, agent wrapper, evaluator, catalog, or labels.

Build deterministic multi-turn state management. Parse positive and negative
constraints, detect Boundary before negative parsing, and reset only on strong
replacement signals. Never reset on "actually" alone. Implement policy config
with simulator_optimized as default: ask other repeatedly until explicit
"no additional preference for other", then ask permitted specific attributes.
Never ask category or brand; turn 10 returns None. Add all listed regression
tests and report APIs, changed files, test command, and result.
~~~

### C — Evaluation, Quality & Optional Semantic Retrieval Engineer

#### 1) 这个人做什么、在链路中的作用和最终结果

C 的主要职责不是 Day 1 就训练 model，而是证明每一次改动是否真的提升官方分数。这样 Day 1–2 C 不会空转，团队也不会凭主观 demo 判断“更智能”。

在 P0/P1 阶段，C 输出 results.json 分析：Hit Rate@10、MRR、MTTC、四类 scenario 分数、失败样本类型和 E0/E1/E2 对比。只有 E2 超过 baseline，C 才实现 P2 Dense Retrieval 与 RRF。

#### 2) 要创建哪些 file，每个 file 要包含什么

**analysis/summarize_results.py**

这是 evaluator 结束后才运行的离线脚本，不会被 Agent import。

- 读取官方 results.json，其中有每个 public session 的 hit、rank、turn 与 scenario。
- 输出 overall metrics、Buying/Browsing/Intent Override/Boundary 分组指标、命中 rank 分布与失败列表。
- 支持对比两个或多个结果文件，输出 E0、E1、E2、E3 差异表。
- 输出可直接复制到 docs/experiment_log.md 的 Markdown summary。
- 只读结果，不修改 evaluator 结果，不向 Agent 反向写入任何标签信息。
- 不试图将随机 session_id 与 sample_id 的 runtime trace 连接；本项目没有 persistent Agent Trace。

**tests/test_analysis.py**

使用构造的小 results.json fixture，测试空结果、miss、rank、scenario grouping、差异比较和稳定 Markdown 输出。不需要 catalog、model 或网络。

**src/semantic.py**（仅 P2 gate 通过后创建）

- 定义 DenseRetriever(enabled: bool)。dense retrieval 是将 query 与商品文本变成 embedding，再用 vector similarity 找语义相近商品；它补充 A 的 lexical route，不替代 A。
- 固定使用 BAAI/bge-small-en-v1.5；优先 MPS，失败回退 CPU。
- 模型、依赖或 weights 不可用时，enabled=False 并返回空 route，绝不抛 exception。
- 启动时使用 A 的 all_documents() 编码 50k search_text；每轮只编码 B 的 cumulative query，输出 Dense Top-200 和 rank。
- 实现 rrf_fuse(lexical, dense)；融合后调用 A 的 ConstraintRanker。C 不输出最终 Top-10，不修改 SessionState。

**tests/test_semantic.py**（仅 P2）

使用 fake encoder 测试 disabled mode、Top-K、去重、RRF 与 lexical fallback。测试不得下载 Hugging Face model。

#### 3) 如何与其他 technician interact、写文件时注意什么

- C 从 D 获取 evaluator 输出路径与 experiment version；analysis 只读结果，不能借 public labels 改 production algorithm。
- C 消费 A 的 ProductDocument.search_text / Candidate，消费 B 的 last_query；不复制 catalog loader、parser 或 ranking。
- C 将 Dense ranks 交给 A 的 unified reranker；D 决定 feature flag，C 不改 src/agent.py。
- C 每日向团队报告 score、scenario regression、runtime 和“保留/关闭”结论。P2 无收益时应明确建议关闭。

#### 4) 如何与自己的 Coding Agent 沟通

先让 Coding Agent 完成 analysis；只有 E2 gate 通过才授权写 semantic。不要一次要求它下载模型、写 RRF 和调参。

~~~text
Phase 1: You are Engineer C. Implement only analysis/summarize_results.py and
tests/test_analysis.py. Read evaluator-produced results.json and report overall,
per-scenario metrics, failures, and experiment deltas. It must be offline,
deterministic, read-only, and never import production Agent code.

Phase 2 is authorized only after E2 beats the baseline. Then implement only
src/semantic.py and tests/test_semantic.py. Use a fake encoder in tests; no
downloads or network calls. Return Dense Top-200 ranks, fuse with lexical ranks
using RRF, and let the existing constraint ranker make final ranking. Report
changed files, tests, metrics comparison, runtime, and keep/disable decision.
~~~

### D — Integration, Configuration & Delivery Engineer

#### 1) 这个人做什么、在链路中的作用和最终结果

D 负责入口、最终 response 和交付闭环。A/B/C 单独正确不代表 evaluator 能运行：官方只 import starter.agent.Agent，schema error、重复 ID 或 optional exception 都会造成 miss。

最终结果是一个可安装、可断网复现的 submission package：官方命令能运行，Agent 按固定顺序组装模块，每轮有合法 Top-10 和 allowed ask_attribute，并带有结果、实验记录、README 与 demo 材料。

#### 2) 要创建哪些 file，每个 file 要包含什么

**src/types.py 与 src/config.py**

- 按第 2.2 节创建冻结的 shared dataclass、allowed attributes、QuestionPolicyConfig、retrieval limit 和 SEMANTIC_ENABLED feature flag。
- 默认 config：mode="simulator_optimized"、final_turn=10、SEMANTIC_ENABLED=False、color_conflict_mode="positive_evidence_only"。D 将主办方 Q&A 的答复集中记录并映射为 config，不在 src.agent.py 中散落 special case。
- 所有开关是本地 config，不依赖 API key 或网络。

**starter/agent.py 与 src/agent.py**

- starter/agent.py 仅 re-export，所有业务逻辑只维护在 src.agent.Agent。
- Agent.__init__(catalog_path) 初始化 A 的 catalog、B 的 manager/policy、config 与 C 的 optional retriever；缺失 catalog 或少于 10 个 unique parent_asin 时必须 fail fast。
- reset(session_id, user_profile) 必须建立独立 state。
- respond(session_id, user_message, turn, top_k) 严格按第 2.4 节顺序调用；retriever/ranker 的 runtime exception 必须使用 A 的 stable fallback 返回合法结果。
- 返回 string message、allowed ask_attribute 或 None、按顺序的 recommendations、以及本地路径零 token usage。
- 不写 persistent Trace、不读 labels、不写 catalog。

**tests/test_agent_e2e.py**

- 使用 temporary catalog 和 fake modules 测试初始化、reset-required、合法 response schema、重复/无效 ID 清除、空 query、Turn 10、semantic exception 与两个 session 隔离。
- 加 import test，确认 from starter.agent import Agent 指向真实实现。

**docs/experiment_log.md、README.md、requirements.txt**

- experiment_log：记录 experiment ID、commit hash、config、overall/scenario metrics、runtime 和保留/关闭结论。
- README：Python version、安装、catalog 路径、官方 evaluator 命令、offline fallback、可选 dense 条件、最终指标、限制和 demo 流程。
- requirements：P0/P1 只含必要依赖；P2 的 sentence-transformers、torch、numpy 作为可选安装项说明。

#### 3) 如何与其他 technician interact、写文件时注意什么

- D 唯一修改 types.py、config.py、agent.py、starter/agent.py、README 与依赖清单；其他人用 issue/PR 提议。
- D 等 A/B API 稳定后再集成，不能在 Agent 内复制 parsing 或 ranking code。
- D 向 C 提供版本化 results 文件，向团队发布每日 main 和冻结 config。
- D 必须将 semantic failure 限制在 local fallback 内，不能让 P2 破坏 P0/P1。
- D 审核所有 PR：不得提交 API key、model cache、public-label mapping、改过的 evaluator 或临时结果。

#### 4) 如何与自己的 Coding Agent 沟通

先让 Coding Agent 建最小 importable skeleton，再等待 A/B merge；不让它凭空实现他人模块。

~~~text
You are Engineer D. Own only src/types.py, src/config.py, src/agent.py,
starter/agent.py, tests/test_agent_e2e.py, docs/experiment_log.md, README.md,
and requirements.txt. Do not modify evaluator, data, retrieval, state, policy,
or semantic implementation.

Create the official Agent adapter and configuration defaults. Agent accepts
catalog_path, follows the official reset/respond contract, and always returns
schema-valid unique catalog IDs through local fallback. Default to
simulator_optimized and semantic disabled. Do not write persistent traces, read
labels, call network services, or add API keys. Use fakes/mocks for e2e tests.
Report integration assumptions, changed files, tests, and results.
~~~

---

## 4. 四天排期、合并与验收

### Day 1 — 让所有人能在同一张地图上工作

| Owner | 当天工作 | 当天预期结果 |
|---|---|---|
| D | 解压 kit、校验 checksum、验证 FTS5、复现 E0；创建 shared types/config/adapter skeleton | catalog 路径与 FTS5 可用；python -m evaluator.local_evaluator 复现 0.10671；所有人可 import shared contract |
| A | ProductDocument、safe flatten、FTS5 最小 index 与 tests | 50k catalog 稳定加载；null/空字段不崩溃 |
| B | parser、state skeleton、Boundary/Override unit tests | 同 session 能累积 slots；不同 session 不串数据 |
| C | results analysis skeleton 与 fixture；核对 evaluator 问答 | 能读 results.json 并按 scenario 汇总；明确 other/Override regression cases |

**Day 1 Git 规则**

1. D 先推送唯一 scaffold commit：chore: initialize agent contracts。
2. 每人从最新 main 创建 feat/a-catalog、feat/b-state-policy、feat/c-analysis、feat/d-integration branch。
3. 每完成一个可测试单元就 push；commit 只包含 owner 文件，例如 feat(A): add FTS catalog index。
4. Push 前运行自己的 tests；PR 写 changed files、接口、tests、风险。D 只 merge 不冲突的 skeleton/unit-test PR。

### Day 2 — 做出可提交的 Offline Agent

| Owner | 当天工作 | 当天预期结果 |
|---|---|---|
| A | Top-200 lexical retrieval、constraint rerank、Top-10 validation | query、negative、null price、稳定排序、positive-evidence-only color 均有 test |
| B | strict Override 与两种 policy mode；默认 other-until-exhausted | actually 不 reset；Boundary 后重问 other；Turn 10 为 None |
| C | E0/E1/E2 comparison、失败分组与 Markdown summary | 团队知道分数变化来自哪个 scenario |
| D/PM | 将已收到的 Q1、Q2、Q6、Q8、Q9 答复记录到 experiment_log，并冻结相应 config | 对 simulator、template、parent variant、metric 与 external-data 边界形成已确认记录；runtime、model weights 与 P2 提交边界仍待确认，不阻塞 E2 |
| D | 集成 A+B，跑 E1/E2，写 experiment log 与 e2e tests | 断网完整 evaluator 可跑；E2 目标超过 E0 |

**Day 2 Git 规则**

1. A/B PR 必须在 D integration 前 merge。
2. 合并顺序固定：D scaffold → A catalog/retrieval → B state/policy → D integration → C analysis。
3. 每个 merged PR 运行 owner tests；D integration PR 附官方 evaluator 输出摘要。
4. E2 分数下降的 PR 不进 main，保留 branch 与 analysis，不能用主观 demo 覆盖指标。

### Day 3 — 只加入可验证的增益

| Owner | 当天工作 | 当天预期结果 |
|---|---|---|
| A | 按 C 报告微调 field weight、constraint bonus、query fallback | 不降低 Buying/Override 的已验证表现 |
| B | 修复 Browsing、Boundary、Override regression；验证 config 切换 | 两种 mode 均可预测运行 |
| C | 仅当 E2 > E0 且 Q4/Q5 不排除提交时实现 Dense Top-200 + RRF，并测 runtime | E3/E2 有完整对比；无收益或环境/提交边界不允许则关闭 |
| D | 启用/关闭 P2 feature flag，集成最终候选 | main 可断网、可评分；semantic 永远可关闭 |

**Day 3 Git 规则**

1. 上午冻结 E2 tag/commit，所有调参在独立 branch。
2. P2 PR 必须有 E2 vs E3 的 overall、四类 scenario、runtime、内存观察、disabled-mode test。
3. 仅 E3 总分严格更高且 offline fallback 通过时 D merge；否则保持 semantic disabled，main 回到 E2。
4. 禁止加入 reranker、外部 API 或 fine-tuning。

### Day 4 — 冻结、验证、展示

| Owner | 当天工作 | 当天预期结果 |
|---|---|---|
| A | catalog path、ID validation、排序稳定性最终检查 | 无无效或重复 parent_asin |
| B | state/policy 最终回归，重点 Override 和 other exhausted | 10-turn 边界与 allowed attribute 无异常 |
| C | 最终 results summary、scenario 对比、限制说明 | 可解释最终分数与保留模块 |
| D | 断网复现、release tag、README、demo walkthrough、提交检查 | 干净环境可安装、运行、复现 |

**Day 4 Git 规则**

1. 上午创建 release-candidate branch；除 blocker bug 外不再加功能。
2. 每个 blocker fix 单独 commit，并附完整 evaluator 复跑。
3. D 在所有验收通过后 merge main、添加 tag；不 squash 掉 experiment evidence。
4. main/tag 不含 API key、model cache、public-label mapping、改过的 evaluator 或临时结果。

---

## 5. 统一验收清单与额外防冲突措施

### 5.1 最终验收

- 官方命令能 import starter.agent.Agent 并完成 200 条 public session。
- 每轮 response 有 string message、allowed ask_attribute，并恰好有 10 个有效且唯一 parent_asin；候选不足时由稳定 fallback 补齐。
- Turn 1–9 默认持续 other，直到真正 exhausted；Turn 10 才返回 None。
- 使用 released template 回归 other-until-exhausted：首次 no preference 后继续请求 other，只有 no additional preference 才视为 exhausted。
- `actually` 单独出现不 reset；明确替换意图会清空旧 preference state，但 replacement turn 未提供新 category 时保留当前 product family category；replacement 旧侧 value 不得重新进入 state。
- black 等明确 color 命中可加分；non-match、多色、缺失或不可靠 color 均中性，不做 penalty 或 hard filter。
- category、brand 不主动询问，但可用于 ranking。
- price=None 保留候选；negative token 不进 FTS 正向 query。
- 无网络、无 optional model、SEMANTIC_ENABLED=False 时 P0/P1 完整运行。
- 启用 P2 时必须满足 Top-200 + Top-200 → RRF → unified constraint rerank，并有更高官方分数、可接受 runtime，以及主办方确认的提交边界证据。
- 使用 released local evaluator 回归 Intent Override、Boundary、metric、stopping rule 与 invalid-output handling。
- source code 不读取 ground_truth、sample_id、scenario label 或 private artifact。

### 5.2 每天 15 分钟 stand-up 模板

每位 technician 回答：

1. 昨天 merge 了什么？对应 test 与 evaluator 指标是什么？
2. 今天交付哪个 file/function？依赖谁的接口？
3. blocker 是 data、contract、score regression 还是环境？
4. 是否需要 D 冻结或修改 shared contract？

PM/D 将答案写入 experiment_log 或当天 issue，避免口头决定丢失。

### 5.3 主动规避的问题

- 不要把 other 的公开 simulator 优势写死在多处；只由 QuestionPolicyConfig 控制。
- 已确认 parent_asin 是可能包含多个 SKU variant 的 parent product；因此不得因相反 color 做 penalty 或 hard filter，只使用明确需求 color 的正向 evidence。
- 不要用 actually 单词作为 Override 的唯一触发器。
- 不要让 Dense 下载或 P2 exception 阻塞 offline evaluator。
- 不要把 public label 信息带入 production Agent。
- 不要在两个 Agent 文件维护业务逻辑；只维护 src.agent.Agent。
- 不要跳过 PR 与 evaluator；最常见失败是合并后才发现官方入口未调用新代码。

### 5.4 本计划额外纳入的必要内容

除四人分工、每人 Coding Agent 协作方式、每日任务与 Git push 规则外，本文额外纳入 QuestionPolicyConfig、离线 results.json 分析、P2 gate、shared-file ownership 与 release-candidate 流程。这些不扩大 MVP scope，而是保证竞赛提交可复现、可诊断、可安全回退的最小保障。
