# Engineer D Day 1 Handoff Report

> Audience: Engineer A, Engineer B, Engineer C  
> Active implementation branch: `feat/d-integration`  
> E0 baseline: tag `e0-baseline` → `27730cec9cfa0a8b07076ebdf4dd388c1a6ef724`

## 1. D 完成的改动、原因与当前状态

### E0 baseline 已固定在 `main`

| Git object | 内容 | 原因 |
|---|---|---|
| `27730ce` / `e0-baseline` | verified unmodified `starter/agent.py`、team plans、official reference docs、README、experiment log | 唯一 E0 source snapshot；后续 E1/E2/E3 必须与它比较。 |
| `ed5d9af` | 在 `docs/experiment_log.md` 写入 E0 source commit 与 tag | 实验记录能精确指向 baseline source，而不是口头说明。 |

E0 已复现 `TechnicalScore = 0.106710`。完整 overall / per-scenario metrics 在 `docs/experiment_log.md`；后续 run 不得重命名或覆盖 E0。

### Repository hygiene

`.gitignore` 已排除 frozen `data/`、official `evaluator/`、participant-kit zip、root `results.json`、`artifacts/`、local model / embedding artifacts、cache 与 `.DS_Store`。Git 只保存 source、tests、config、decision record 与文档。任何人本地可从 verified kit 下载 artifact，但不得提交 data、public evaluation output 或 generated model artifact。

### D scaffold 在 `feat/d-integration`

Commit `646f135` 创建：

| File | 当前责任 |
|---|---|
| `src/types.py` | D-owned shared `Candidate`、`ParsedTurn`、`SessionState` dataclass；Day 3 前字段名冻结。 |
| `src/config.py` | D-owned constants、`QuestionPolicyConfig`、`RankingConfig`、`RETRIEVAL_LIMIT=200`、`SEMANTIC_ENABLED=False`。 |
| `src/agent.py` | official interface skeleton、per-session storage、zero-token response shape；不复制 A/B/C algorithm。 |
| `starter/agent.py` | 仅 `from src.agent import Agent`，是 official evaluator 的唯一 entrypoint。 |
| `tests/test_agent_e2e.py` | import path、reset-required、session isolation、Turn 10 scaffold behavior 的 test skeleton。 |

当前 scaffold 是 **importable integration base，不是可评分 MVP**。它刻意没有 A retrieval 或 B policy，因此 recommendations 仍为空；A/B merge 后 D 才能完成 valid Top-10 fallback 与 E1/E2 evaluator run。

### D 使用的文档

- `docs/latest_four_day_implem.md`：当前 implementation authority；重点为 shared contract、call order、owner boundary 与 merge gate。
- `docs/organizer_engineer_qa.md`：主办方答复及其 config decision。
- `docs/experiment_log.md`：E0、后续 E1/E2/E3 metrics、runtime、keep/disable decision 的唯一记录。
- `docs/official_reference/`：official API、scoring、evaluation reference；只读，不修改。

## 2. 与 Engineer A 的关联：retrieval 接入方式

### A 的 branch 与文件迁移

D scaffold merge 前，A 应基于 `origin/feat/d-integration` 建 branch；scaffold merge 后则从 updated `main` 建 `feat/a-catalog`。不要从 `e0-baseline` tag 开发，因为该 tag 没有 shared `src/types.py`。

迁移目标：

```text
EnginnerA/catalog.py       → src/catalog.py
EnginnerA/retrieval.py     → src/retrieval.py
EnginnerA/test_catalog.py  → tests/test_catalog.py
```

### A 必须遵守的 D contract

1. 从 `src.types` import `Candidate`；最终 `src/retrieval.py` 不保留第二份 shared Candidate definition。
2. `Candidate.score` 统一为“越大越相关”；lexical route 写入 `route_ranks={"lexical": rank}`，供 C 的 RRF 使用。
3. `validate_recommendations` 必须接收 `valid_ids` 与 required `fallback_ids`，输出 official recommendation dict；catalog 不能凑足 Top-10 时抛 `catalog integrity error`。
4. config 的 color policy 是 `positive_evidence_only`：desired color 命中才 bonus；non-match、multicolor、missing、description-only、negative color 都不能 penalty 或 hard filter。

### A 如何使用 repo 文档

- 先读 `latest_four_day_implem.md` 的 shared contract、call order、A section 与 final acceptance list。
- 用 `organizer_engineer_qa.md` 确认 parent product / variant color 的原因，不自行改为 color hard filter。
- 从 `experiment_log.md` 获取 C 对 E1/E2 的 score 与 scenario regression，再提 ranking-weight change；不能只按 demo 调权重。
- A 的 reviewed design docs 随 A PR 迁入 `docs/team-notes/`，并与 final `src/` code 同步。

A 不得修改 `src/types.py`、`src/config.py`、`src/agent.py`、`starter/agent.py`，也不得提交 data、evaluator、results 或 label-derived logic。

## 3. 与 Engineer B 的关联：state 与 policy 接入方式

### B 的 branch 与目标文件

D scaffold merge 前，B 应基于 `origin/feat/d-integration` 建 branch；merge 后从 updated `main` 建 `feat/b-state-policy`。B 的 production files 是：

```text
src/state.py
src/policy.py
tests/test_state_policy.py
```

### B 必须遵守的 D contract

1. 使用 `src.types.SessionState` 和 `ParsedTurn`，不建立同名或字段不同的版本。
2. slot key 固定为 `category/material/color/size/style/brand/budget/feature/use_case`。
3. `QuestionPolicyConfig` 默认 `mode="simulator_optimized"`、`final_turn=10`；B 的 policy 必须读取 config，而非在 `src.agent.py` 写死策略。
4. Turn 1–9：`other_exhausted=False` 时请求 `other`；首次 `no preference for other` 不 exhausted，只有 `no additional preference for other` 才 exhausted。
5. Turn 10：`ask_attribute=None`；category 与 brand 永不主动询问。
6. Override 只接受 strong replacement signal；`actually` 单独出现或普通补充不能 reset current intent。

### B 如何使用 repo 文档

- `latest_four_day_implem.md` 的 B section 是 parser / policy functional specification。
- `official_reference/agent_api_contract.json` 定义 allowed `ask_attribute`，B tests 必须覆盖输出合法性。
- organizer Q&A 与 experiment log 已确认 public/private template、repeated `other`、metric behavior 一致，因此 default `simulator_optimized` 当前应保持不变。

B 向 D 交付 parsed slots、updated `SessionState`、`last_query`、`ask_attribute` 与 English message template；D 只负责 official response schema，不复制 parser、Override 或 question selection logic。B 若要改 shared fields，必须先提出 contract change。

## 4. 与 Engineer C 的关联：evaluation 与 gated semantic retrieval

### C 的 Phase 1

C 可独立创建：

```text
analysis/summarize_results.py
tests/test_analysis.py
```

它读取本地 evaluator 生成的 local `results.json`，但不得提交 raw results、session mapping 或 public labels。C 应提交 deterministic analysis code，并把 Markdown summary 写入 `docs/experiment_log.md`。

### C 必须遵守的 D contract

1. E0 comparison point 永远是 `e0-baseline` / `27730ce`；不以 active branch 临时 score 重定义 baseline。
2. 每个 E1/E2/E3 run 记录 commit hash、config snapshot、overall、four-scenario metrics、runtime 与 keep/disable decision。
3. P2 仅在 E2 严格高于 E0，且 runtime / model-package gate 不阻止 submission 时开始。
4. P2 固定顺序：`Lexical Top-200 + Dense Top-200 → RRF → A ConstraintRanker → D validation`。
5. C 使用 A 的 `CatalogIndex.all_documents()` 与 `Candidate.route_ranks`；不复制 catalog loader，不改 `src/agent.py`、`src/config.py` 或 validator。D 控制 `SEMANTIC_ENABLED`。

### C 如何使用 repo 文档

- `experiment_log.md` 是 append-only experiment decision record；C 将 analysis summary 写入对应 run section。
- `official_reference/evaluation_config.json` 与 `competition_specification.md` 是 metric、stopping rule、scenario reference。
- `latest_four_day_implem.md` 的 C section定义 P2 gate；P2 无 strict gain 或 disabled-mode 不通过时，C 必须建议保持 `SEMANTIC_ENABLED=False`。

## 下一次 merge 前的协调规则

`feat/d-integration` 尚未 merge 到 `main`。推荐顺序：

1. Team review D scaffold。
2. D 创建 / merge scaffold PR 到 `main`。
3. A、B 从 updated `main` 建 feature branch；C 可并行开始 analysis。
4. A/B PR merge 后，D 完成 official Agent assembly、e2e validation 和 E1/E2。

在 step 2 前，A/B 可 inspect 或临时基于 `origin/feat/d-integration` 开发，但不要从 `e0-baseline` tag 开发 production code。
