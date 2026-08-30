# 主办方 Engineer Q&A：竞赛关键问题清单

> 用途：由 PM 或 D 在 Day 1 尽早向主办方 Engineer 提问。本文记录会改变 MVP 技术路线、提交形式或排序安全性的未确认事项。收到回复后，D 将结论登记到 `docs/experiment_log.md`，并按本文的决策表更新本地 `config.py`，而不是在多处修改 Agent 逻辑。

## 1. 结论与优先级

以下问题会直接影响是否保留 `other-until-exhausted`、是否需要提前做 `Dense Retrieval`、能否提交本地 model / derived index，以及颜色冲突的排序逻辑。建议优先问问题 1–6；在答复前，维持 Offline P0/P1 和保守排序，不阻塞 Day 1–2 实施。

## 2. 必问问题

### Q1. private customer simulator 与公开 `local evaluator` 的一致性

> Will the private evaluator use the same `ask_attribute` response policy as the released local evaluator, including repeated `"other"` requests and the distinction between “no preference” and “no additional preference”?

**为什么会影响实现：** 公开 evaluator 让 `other` 连续暴露未披露约束，因而 `other-until-exhausted` 是高信息量策略。private policy 若不同，当前 `simulator_optimized` 默认值可能失效。

| 主办方答复 | D 的配置动作 | B 的策略动作 |
|---|---|---|
| 与公开 evaluator 相同 | 保持 `QuestionPolicyConfig.mode="simulator_optimized"` | Turn 1–9 持续请求 `other`，直到 `other_exhausted=True` |
| 不同或不保证一致 | 改为 `mode="information_gain"` | 用候选属性覆盖度选择 `material`、`color`、`size`、`style`、`feature`、`use_case`、`budget`；不主动问 `category`、`brand` |

### Q2. private user message 是否含 natural-language paraphrase

> Will private user messages follow the released templates, or include natural-language paraphrases? If paraphrases are used, can you provide representative examples or an updated local evaluator?

**为什么会影响实现：** 若模板不变，deterministic `regex parser` 已足够覆盖核心流程；若存在自然语言改写，slot extraction、Boundary 与 `Intent Override` 的 recall 风险会升高，`Dense Retrieval` 的优先级也会提高。

**收到答复后的动作：** 保持 `regex parser` 为 P0/P1；若存在改写，B 在不引入外部 `LLM` 的前提下补充 synonym / phrase tests，C 将 P2 作为 Day 3 优先实验，但仍须通过 E2/E3 gate 才可进入 main。

### Q3. `message` 的作用范围

> Does final evaluation consume only the structured `ask_attribute`, or can the natural-language `message` affect customer replies or receive automated scoring?

**为什么会影响实现：** 若 evaluator 只读取 `ask_attribute`，英文 `message` 应使用稳定、简短 template；若 `message` 会影响 simulator 或自动评分，则需要针对语义、格式和措辞增加测试。

**收到答复后的动作：** 默认把 `message` 视为展示层，继续使用 `render_message()` template；只有主办方明确说明它参与评分或 simulator 时，才将 message contract 纳入 B/D 的 regression tests。不会因此引入 runtime `LLM`。

### Q4. 最终运行环境与 timeout

> What are the final execution limits: Python version, CPU/GPU/MPS availability, RAM, initialization timeout, per-turn timeout, total runtime, and network access?

**为什么会影响实现：** 这决定 50k catalog 的 embedding 能否在启动时构建、是否能使用 `MPS`、以及 P2 的实际延迟是否可接受。

**收到答复后的动作：** P0/P1 一律保持 `SQLite FTS5` 的 offline path；C 只有在环境确认且 E3 提升时保留 `Dense Retrieval`。若无 GPU / MPS、启动或每轮 timeout 紧，保持 `SEMANTIC_ENABLED=False`。

### Q5. pretrained model weights 与 catalog-derived artifact 的提交边界

> May teams bundle pretrained model weights or catalog-derived embedding/index artifacts? Are there package-size limits, and must all derived indexes be built in memory at startup?

**为什么会影响实现：** `Dense Retrieval` 需要 model weights 和 catalog embedding / vector index。能否预计算、是否有体积限制会决定其是否可提交，而不仅是本地能否运行。

**收到答复后的动作：** 未获明确允许前，不提交 model cache 或 embedding artifact；P2 仅作本地实验。即使被允许，也只使用 frozen catalog 衍生的 artifact，并在 README 中记录构建方式、大小、hash 与 offline fallback。

### Q6. `parent_asin` 的 color / variant 语义

> Does each catalog `parent_asin` represent one concrete color/size variant, or a parent product with multiple variants? Are private intent cards derived from exactly the same metadata record exposed to participants?

**为什么会影响实现：** 一个 `parent_asin` 若包含多个 color / size variant，商品文字中出现 `red` 不代表该 parent 不满足 `black`。若 intent card 也不完全来自公开 metadata，不能把未观察到的属性当作强反证。

**收到答复后的动作：** 在答案明确前维持三值 `Conflict Scoring`（见第 4 节）。只有主办方确认一条 `parent_asin` 对应单一、可靠的 concrete variant 后，团队才可在独立 experiment 中测试 `hard constraint`；仍须证明 E2/E3 不回归才可合并。

## 3. 建议继续问的合规与评分问题

### Q7. `LLM Semantic Ranking` 是否为强制要求

> Is “LLM Semantic Ranking” a mandatory requirement for final scoring, or can an offline hybrid retriever without an LLM receive full Technical Execution credit?

**影响与默认：** 关系到 human judging 的合规解释。默认不接外部 `LLM`；若 offline hybrid 可获完整 Technical Execution credit，保持当前 P3 排除范围。

### Q8. 最终评分与本地 config 的一致性

> Will the final evaluator use the same metric formula, stopping rule, invalid-output handling, and timeout behavior as the released local evaluator?

**影响与默认：** 决定 public evaluator 的可靠程度。默认以 released evaluator 作为唯一可测 proxy；若存在差异，D 将新增对应 contract regression test，并重新评估每轮恰好 Top-10、Turn 10 `null` 的行为。

### Q9. 外部数据边界

> Apart from pretrained models, may teams use the upstream Amazon Reviews 2023 data or other public corpora for preprocessing, or must retrieval features be derived only from the frozen catalog?

**影响与默认：** 决定是否可扩展 metadata；也关系到数据公平与复现。默认 production retrieval 仅从 frozen catalog 派生特征，公开 labels 仅用于 evaluator 与离线 analysis，不下载或接入上游 reviews。

## 4. 已采用的 algorithm 规则

### 4.1 color 的三值 `Conflict Scoring`

当用户明确要求 `black` 时，排序逻辑不进行一刀切的 color filter，而是按 metadata 可靠度分三种情况：

| 商品中的 color 证据 | 排序处理 | 原因 |
|---|---|---|
| 有明确 `black` | 加分 | 是直接的正向匹配 |
| 有明确、单一且可信的非 `black` color | 小幅减分 | 是可能冲突，但在 variant 语义未确认前不能直接删除 |
| color 缺失、字段不可靠、多个 color 或仅在 description 中出现颜色词 | 不加不减 | 颜色词可能是图案、材质描述或同一 parent 的其他 variant |

实现边界：A 将此实现为可配置的 metadata bonus / penalty，且只基于 `extract_attributes()` 标为可靠的 color。不得把任意 `description` 中的 `red`、`white` 视为冲突；不得在 Q6 未获答复前把 non-black 作为 `hard constraint`。

### 4.2 不做 turn-based ranking bonus

“命中轮数越前，分数越高”是正确的竞赛判断，但无需给 Candidate 人为附加 turn score。官方 `MTTC` 与 `Efficiency` 已自动奖励早命中；人为 bonus 既没有新增信息，也可能破坏后续轮的排序。

工程上应落实为：

1. Turn 1 起每轮同时返回当前最佳、有效且唯一的 Top-10，以及一个 `ask_attribute`。
2. 收到新约束后立即重排，绝不等待信息收集完成再推荐。
3. Turn 10 返回 `ask_attribute=null`，但仍返回最终 Top-10。

## 5. 回复前的默认决定与解除条件

在主办方回复之前，保持以下默认值，不阻塞 Day 1–2：

| 决策项 | 当前默认值 | 何时改变 |
|---|---|---|
| Question policy | `simulator_optimized`，`other-until-exhausted` | Q1 显示 private policy 不同或不保证一致 |
| Color conflict | 保守、小幅 penalty；不 hard filter | Q6 确认 concrete single-variant metadata，且独立实验提升 |
| Dense Retrieval | P2，本地 gated experiment；`SEMANTIC_ENABLED=False` | E2 优于 E0、Q4/Q5 允许、并且 E3 严格优于 E2 |
| External `LLM` | 不引入 | 仅主办方明确强制且团队另行批准 |
| External data | 不使用 | Q9 明确允许且团队确认收益/合规性 |

## 6. 记录与责任

- **PM / D：** 发送问题、保存文字答复或官方链接，并将 Q 编号、答复日期、决定、影响的 config / commit 记入 `docs/experiment_log.md`。
- **B：** 仅根据 Q1 结论切换 `QuestionPolicyConfig.mode`；不得把 public simulator 行为硬编码到 parser 或 Agent。
- **A：** 仅根据 Q6 结论在独立 branch 试验 `hard constraint`；默认三值 `Conflict Scoring`。
- **C：** 根据 Q2、Q4、Q5 报告 P2 可行性、runtime 与 E2/E3 数据；不能用主观 demo 决定合并。
- **D：** 负责把最终决定集中在 `config.py`、README、experiment log，并确保 P0/P1 offline fallback 始终可运行。
