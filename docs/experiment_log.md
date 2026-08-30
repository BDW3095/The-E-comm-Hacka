# Experiment Log

This log records reproducible evaluator experiments and environment preflight. It is an offline record only; production Agent code must not read it or use public labels.

## Environment preflight — 2026-08-29

| Check | Result | Evidence |
|---|---|---|
| Official participant kit layout | PASS | Root contains official `data/`, `evaluator/`, and `starter/`. Official reference documents were copied to `docs/official_reference/` so existing team documents were not overwritten. |
| Participant-kit SHA256 | PASS | `b3d7e283b835343b42c4919ea2ca90f2fb5a2aa2b10537f14dcf42f03e5b38ae`, matching `official_participant_kit/SHA256SUMS`. |
| Frozen catalog and public set | PASS | `data/catalog.jsonl` has 50,000 JSONL records; `data/public_set.jsonl` has 200 records. Frozen catalog was copied from the verified participant kit, not rebuilt from upstream data. |
| Python / SQLite | PASS | Python 3.11.9; SQLite 3.45.1. |
| SQLite FTS5 | PASS | Created, inserted into, and queried an in-memory FTS5 virtual table. |

## E0 — Official starter baseline

- Date: 2026-08-29
- E0 source commit: pending baseline snapshot commit; this value will be replaced in the follow-up documentation commit.
- Git tag: pending `e0-baseline` tag.
- Code state: unmodified official `starter/agent.py` copied from the verified participant kit.
- Command: `python3 -m evaluator.local_evaluator`
- Network: not used.

| Metric | Value |
|---|---:|
| Sample count | 200 |
| Hit Rate@10 | 0.125000 |
| MRR | 0.068034 |
| MTTC | 9.810000 |
| Efficiency | 0.119000 |
| TechnicalScore | **0.106710** |

| Scenario | Sample count | Hit Rate@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| Boundary | 10 | 0.000000 | 0.000000 | 11.000000 |
| Browsing | 80 | 0.025000 | 0.004514 | 10.750000 |
| Buying | 80 | 0.237500 | 0.126508 | 8.625000 |
| Intent Override | 30 | 0.133333 | 0.104167 | 10.066667 |

## Frozen decisions after preflight

- E0 remains the comparison baseline; later runs must be labeled E1, E2, or E3 and must not replace E0.
- P0/P1 must remain offline and must use SQLite FTS5 lexical retrieval.
- Default `QuestionPolicyConfig.mode` will be `simulator_optimized`.
- Default `RankingConfig.color_conflict_mode` will be `positive_evidence_only`: desired-color evidence may receive a bonus; non-match, multicolor, missing, and unreliable color evidence remain neutral.
- `SEMANTIC_ENABLED` remains `False` until the E2/E3 score gate and runtime / model-package submission limits are confirmed.

## Open gates

- Final runtime limits, network policy, model-weight packaging, derived-index packaging, and package-size limits remain unconfirmed.
- These unresolved P2 conditions do not block P0/P1 implementation or the E2 offline evaluation.
