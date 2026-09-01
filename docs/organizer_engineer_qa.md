# 主办方 Engineer Q&A：确认答复与当前决策

> 本文记录会改变 MVP 技术路线的 organizer 答复。当前 production 行为以
> `docs/latest_four_day_implem.md`、`docs/experiment_log.md` 与 `src/` 为准；未确认事项不得阻塞 Offline P0/P1。

## 已确认答复

| 问题 | 主办方答复 | 已冻结的工程决定 |
|---|---|---|
| Q1: private simulator policy | 与 released local evaluator 相同。 | 保持 `QuestionPolicyConfig.mode="simulator_optimized"`；Turn 1–9 执行 `other-until-exhausted`。 |
| Q2: private message templates | 使用 released templates；没有 natural-language paraphrase。 | 保持 deterministic `regex parser`，不引入 runtime LLM。 |
| Q6: `parent_asin` variant 语义 | `parent_asin` 是 parent product，不是具体 color 或 size SKU。 | `color_conflict_mode="positive_evidence_only"`：明确 desired color 才加分；non-match、多色、缺失与不可靠 color 均中性，不做 penalty 或 hard filter。 |
| Q8: evaluator metrics / stopping / invalid output | 与 released local evaluator 相同。 | released evaluator 是 P0/P1 的唯一 acceptance proxy；每轮必须输出 10 个 unique、catalog-valid ID，Turn 10 仅返回 `ask_attribute=null`。 |
| Q9: external data | 可以使用，但不得 reconstruct inner-label。 | production 继续只使用 frozen catalog；public labels 只用于 evaluator 和 offline analysis。 |

## 仍未确认的事项

### Q3. `message` 的作用范围

> Does final evaluation consume only the structured `ask_attribute`, or can the natural-language `message` affect customer replies or receive automated scoring?

当前动作：`message` 保持稳定、简短的 `render_message()` template；不引入 runtime LLM。

### Q4. 最终运行环境与 timeout

> What are the final execution limits: Python version, CPU/GPU/MPS availability, RAM, initialization timeout, per-turn timeout, total runtime, and network access?

当前动作：保持 SQLite FTS5 Offline path；`SEMANTIC_ENABLED=False`。

### Q5. model weights 与 derived index 的提交边界

> May teams bundle pretrained model weights or catalog-derived embedding/index artifacts? Are there package-size limits, and must all derived indexes be built in memory at startup?

当前动作：不提交 model cache、embedding 或 derived index；P2 仅在 Q4/Q5 明确允许且独立 experiment 通过后才可实施。

### Q7. `LLM Semantic Ranking` 是否强制

> Is “LLM Semantic Ranking” a mandatory requirement for final scoring, or can an offline hybrid retriever without an LLM receive full Technical Execution credit?

当前动作：不接 external LLM；P3 继续排除在 MVP 外。

## 当前 algorithm 规则

### `positive-evidence-only` color

用户要求 `black` 时：

- 明确 structured `black` evidence：加分；
- 其他 color、多色、缺失或不可靠 evidence：中性；
- 不做 color penalty，也不做 color hard filter。

原因是一个 `parent_asin` 可能覆盖多个 SKU variants；non-match color 不是负向证据。

### 不做 turn-based ranking bonus

官方 `MTTC` 和 `Efficiency` 已奖励早命中。Agent 从 Turn 1 起同时返回当前最佳 Top-10 和 `ask_attribute`；Turn 10 仍返回 Top-10，只将 `ask_attribute` 设为 `null`。

## P2 gate 与责任

- P2-Dense 只有在官方 runtime/package 限制确认、local experiment 严格优于现有 lexical baseline、且 disabled path 通过 regression 后才可进入 production。
- PM/D 记录答复、config 与 experiment evidence。
- B 仅通过 `QuestionPolicyConfig` 响应 Q1。
- A 不得对 non-match color 建立 penalty 或 hard filter。
- C 的 analysis 只能读取 evaluator output，不能把 sample ID、ground truth 或 scenario 反馈到 production ranking。
