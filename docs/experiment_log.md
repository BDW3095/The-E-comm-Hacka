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
- E0 source commit: `27730cec9cfa0a8b07076ebdf4dd388c1a6ef724`
- Git tag: `e0-baseline`
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

## E1 — Deterministic A/B/D integration

- Date: 2026-09-01
- E1 source commit: `a3636cff5564bb1513bcaa5b9561c07c12a94fa6`
- Branch: `feat/e1-agent-integration` (local; not pushed at recording time)
- Code state: B state update → A lexical Top-200 → A constraint rerank → B question policy → D validation/official response assembly.
- Command: `python3 -m evaluator.local_evaluator --output artifacts/e1_results.json`
- Repository tests: `79 passed`.
- Runtime: approximately 52 seconds for 200 public sessions on the local Windows environment.
- Network/model usage during evaluation: none; reported tokens: 0.
- Raw evaluator output: local ignored artifact; not committed.

| Metric | E0 | E1 | Delta |
|---|---:|---:|---:|
| Sample count | 200 | 200 | 0 |
| Hit Rate@10 | 0.125000 | 0.805000 | +0.680000 |
| MRR | 0.068034 | 0.501044 | +0.433010 |
| MTTC | 9.810000 | 3.945000 | -5.865000 |
| Efficiency | 0.119000 | 0.705500 | +0.586500 |
| TechnicalScore | **0.106710** | **0.693913** | **+0.587203** |

| Scenario | Sample count | Hit Rate@10 | MRR | MTTC |
|---|---:|---:|---:|---:|
| Boundary | 10 | 0.900000 | 0.725000 | 4.000000 |
| Browsing | 80 | 0.887500 | 0.536419 | 3.212500 |
| Buying | 80 | 0.887500 | 0.519315 | 2.900000 |
| Intent Override | 30 | 0.333333 | 0.283333 | 8.666667 |

Decision: keep E1 as the first integrated lexical baseline. The dominant E2 target is Intent Override, which accounts for 20 of E1's 39 misses. No public session IDs or labels are used by production code.

## E2 — Preference Override category preservation

- Date: 2026-09-01
- E2 source commit: `e3fa2c64513a6be9d7927397143cb912246783fc`
- Branch: `feat/e1-agent-integration` (local; not pushed at recording time)
- Change: preserve the existing product category when an explicit Override replaces only a preference; replace the category when the new message names a new product category. Also fix the optional-article parser so `accessories` is not truncated to `ccessories`.
- Command: `python3 -m evaluator.local_evaluator --output artifacts/e2_final_results.json`
- Repository tests: `80 passed`.
- Runtime: approximately 53 seconds for 200 public sessions.
- Network/model usage during evaluation: none; reported tokens: 0.
- Raw evaluator output: local ignored artifact; not committed.

| Metric | E1 | E2 | Delta |
|---|---:|---:|---:|
| Hit Rate@10 | 0.805000 | 0.840000 | +0.035000 |
| MRR | 0.501044 | 0.510145 | +0.009101 |
| MTTC | 3.945000 | 3.685000 | -0.260000 |
| Efficiency | 0.705500 | 0.731500 | +0.026000 |
| TechnicalScore | **0.693913** | **0.719343** | **+0.025430** |

| Scenario | E1 Hit@10 | E2 Hit@10 | E1 MRR | E2 MRR | E1 MTTC | E2 MTTC |
|---|---:|---:|---:|---:|---:|---:|
| Boundary | 0.900000 | 0.900000 | 0.725000 | 0.725000 | 4.000000 | 4.000000 |
| Browsing | 0.887500 | 0.887500 | 0.536419 | 0.536419 | 3.212500 | 3.212500 |
| Buying | 0.887500 | 0.887500 | 0.519315 | 0.519315 | 2.900000 | 2.900000 |
| Intent Override | 0.333333 | 0.566667 | 0.283333 | 0.344008 | 8.666667 | 6.933333 |

Ablation: commit `8076aaa` additionally introduced category token-overlap ranking and scored `0.717105`, but reduced Browsing MRR from `0.536419` to `0.514350`. That global bonus was removed in `e3fa2c6`; the final E2 retains the Override gain without regression in Buying, Browsing, or Boundary.

Decision: keep E2. Intent Override misses fall from 20 to 13, total misses fall from 39 to 32, and all non-Override scenario metrics remain unchanged from E1.

## E3 — Cumulative query coverage reranking

- Date: 2026-09-01
- E3 source commit: `17313bee3f3ec192d5c9b629d81c181fc366b4f8`
- Branch: `feat/e1-agent-integration` (local; not pushed at recording time)
- Change: add a label-free query-coverage feature to `ConstraintRanker`. Each candidate receives up to `20.0` points according to the fraction of unique cumulative-query tokens present in its catalog search text. Existing positive/negative attribute rules remain unchanged.
- Command: `python3 -m evaluator.local_evaluator --output artifacts/e3_weight20_results.json`
- Repository tests: `81 passed`.
- Runtime: approximately 61 seconds for 200 public sessions.
- Network/model usage during evaluation: none; reported tokens: 0.
- Raw evaluator output: local ignored artifact; not committed.

| Metric | E2 | E3 | Delta |
|---|---:|---:|---:|
| Hit Rate@10 | 0.840000 | 0.880000 | +0.040000 |
| MRR | 0.510145 | 0.554861 | +0.044716 |
| MTTC | 3.685000 | 3.330000 | -0.355000 |
| Efficiency | 0.731500 | 0.767000 | +0.035500 |
| TechnicalScore | **0.719343** | **0.759858** | **+0.040515** |

| Scenario | E2 Hit@10 | E3 Hit@10 | E2 MRR | E3 MRR | E2 MTTC | E3 MTTC |
|---|---:|---:|---:|---:|---:|---:|
| Boundary | 0.900000 | 1.000000 | 0.725000 | 0.743452 | 4.000000 | 3.200000 |
| Browsing | 0.887500 | 0.937500 | 0.536419 | 0.560813 | 3.212500 | 2.775000 |
| Buying | 0.887500 | 0.925000 | 0.519315 | 0.591682 | 2.900000 | 2.550000 |
| Intent Override | 0.566667 | 0.566667 | 0.344008 | 0.377937 | 6.933333 | 6.933333 |

Ablations:

- Coverage weight `12.0` at commit `cd3260a` scored `0.757779`; weight `20.0` improved overall and every scenario MRR without reducing any scenario Hit@10, so `20.0` is retained.
- A strict all-token FTS route was examined against the 24 remaining E3 misses. Only 4 targets reached that route's Top-10, while many existing E3 hits occur at ranks 6–10; the route was not added because its narrow potential gain did not justify displacement risk.

Decision: keep E3. Total misses fall from 32 to 24, rank-1 hits rise from 79 to 88, and all four scenario groups improve or remain stable relative to E2. Production code uses only current user constraints and catalog text; it does not read public labels, sample IDs, evaluator output, or scenario type.

## Frozen decisions after preflight

- E0 remains the comparison baseline; later runs must be labeled E1, E2, or E3 and must not replace E0.
- P0/P1 must remain offline and must use SQLite FTS5 lexical retrieval.
- Default `QuestionPolicyConfig.mode` will be `simulator_optimized`.
- Default `RankingConfig.color_conflict_mode` will be `positive_evidence_only`: desired-color evidence may receive a bonus; non-match, multicolor, missing, and unreliable color evidence remain neutral.
- `SEMANTIC_ENABLED` remains `False` until the E2/E3 score gate and runtime / model-package submission limits are confirmed.

## E4 V1 — Catalog precision hardening

- Date: 2026-09-01
- E4 V1 source commit: `65b1511e6195e7dda3ee9943518c4f889bde9e92`
- Base: E3 documentation snapshot `b21ec96`
- Branch: `exp/e4-a-b-hardening`
- Changes:
  - Route structured `details` values only to their declared attribute.
  - Keep `store` as brand and FTS5 evidence, but exclude it from structured attribute extraction.
  - Keep full brand phrases and generate only conservative legal-suffix / leading-`the` aliases.
  - Canonicalize hyphen, underscore, and repeated whitespace forms such as `quick-dry`, `quick_dry`, and `quick dry`.
  - Canonicalize `ConstraintRanker` fallback surface text without changing E3 query-coverage reranking.
- Validation:
  - `python -m pytest tests/test_catalog.py -q`: `50 passed`.
  - Full repository regression: passed.
  - `git diff --check`: passed.
- Command: `time python -m evaluator.local_evaluator`
- Runtime: `33.398 seconds` for 200 public sessions.
- Network/model usage during evaluation: none; reported tokens: 0.
- Raw evaluator output: local ignored artifact; not committed.

| Metric | E3 | E4 V1 | Delta |
|---|---:|---:|---:|
| Hit Rate@10 | 0.880000 | 0.880000 | 0.000000 |
| MRR | 0.554861 | 0.554861 | 0.000000 |
| MTTC | 3.330000 | 3.330000 | 0.000000 |
| Efficiency | 0.767000 | 0.767000 | 0.000000 |
| TechnicalScore | **0.759858** | **0.759858** | **0.000000** |

| Scenario | E3 Hit@10 | E4 V1 Hit@10 | E3 MRR | E4 V1 MRR | E3 MTTC | E4 V1 MTTC |
|---|---:|---:|---:|---:|---:|---:|
| Boundary | 1.000000 | 1.000000 | 0.743452 | 0.743452 | 3.200000 | 3.200000 |
| Browsing | 0.937500 | 0.937500 | 0.560813 | 0.560813 | 2.775000 | 2.775000 |
| Buying | 0.925000 | 0.925000 | 0.591682 | 0.591682 | 2.550000 | 2.550000 |
| Intent Override | 0.566667 | 0.566667 | 0.377937 | 0.377937 | 6.933333 | 6.933333 |

Decision: keep E4 V1. The catalog and fallback-matching correctness improvements preserve every E3 public metric and scenario result. E3 query-coverage reranking remains intact. Proceed to V2/V3 replacement-side parser regression work.

## E4 V3 — Replacement-side parser isolation

- Date: 2026-09-01
- E4 V3 source commit: `09f8a21`
- Base: E4 V1 (`65b1511e6195e7dda3ee9943518c4f889bde9e92`) on `exp/e4-a-b-hardening`.
- V2 proof: three new regression tests initially reproduced old-side leakage from replacement statements:
  - `Rather than size M, I need size L` retained `medium` alongside `large`.
  - `Instead of over $50, I need under $100` retained the old minimum budget.
  - `Rather than a short sleeve jacket, I need a waterproof jacket` could retain `short sleeve`.
- V3 change: pass `replaced_value_scopes` through contextual-size, lexical-only-feature, budget, and explicit-raw-feature extraction. Values in the old side of `instead of`, `rather than`, `change from ... to`, or `switch from ... to` are discarded before the new turn is merged. This does not change the existing strong-Override reset, category-inheritance, `actually`, or `other-until-exhausted` rules.
- Validation:
  - Replacement-side regressions: `3 passed`.
  - `python -m pytest tests/test_state_policy.py -q`: `32 passed`.
  - `python -m pytest -q`: `95 passed`.
  - `git diff --check`: passed.
- Command: `python -m evaluator.local_evaluator --output artifacts/e4_v3_results.json`
- Runtime/model usage: local lexical P0/P1 only; no network or model; reported tokens: 0.
- Raw evaluator output and generated comparison: ignored local artifacts `artifacts/e4_v3_results.json` and `artifacts/e4_v1_vs_v3.md`.

| Metric | E4 V1 | E4 V3 | Delta |
|---|---:|---:|---:|
| Hit Rate@10 | 0.880000 | 0.880000 | 0.000000 |
| MRR | 0.554861 | 0.554861 | 0.000000 |
| MTTC | 3.330000 | 3.330000 | 0.000000 |
| Efficiency | 0.767000 | 0.767000 | 0.000000 |
| TechnicalScore | **0.759858** | **0.759858** | **0.000000** |

| Scenario | E4 V1 Hit@10 | E4 V3 Hit@10 | E4 V1 MRR | E4 V3 MRR | E4 V1 MTTC | E4 V3 MTTC |
|---|---:|---:|---:|---:|---:|---:|
| Boundary | 1.000000 | 1.000000 | 0.743452 | 0.743452 | 3.200000 | 3.200000 |
| Browsing | 0.937500 | 0.937500 | 0.560813 | 0.560813 | 2.775000 | 2.775000 |
| Buying | 0.925000 | 0.925000 | 0.591682 | 0.591682 | 2.550000 | 2.550000 |
| Intent Override | 0.566667 | 0.566667 | 0.377937 | 0.377937 | 6.933333 | 6.933333 |

Decision: keep E4 V3. Public metrics are unchanged from E3/E4 V1, while replacement-language correctness and the declared Override contract are now protected by regressions.

## E4 V4 — RankingConfig plumbing

- Date: 2026-09-01
- E4 V4 source commit: `814cb987c8672f51d4073d4d49c0aa2ff4450928`
- Base: E4 V3 documentation snapshot `97ae721` on `exp/e4-a-b-hardening`.
- Branch: `refactor/e4-v4-ranking-config`
- Change: move the existing ranking constants into a validated, frozen `RankingConfig`, inject it through `Agent` into `ConstraintRanker`, and expose an optional constructor argument for offline ablation. Default values preserve the E4 V3 algorithm exactly.
- Default config:
  - `color_conflict_mode="positive_evidence_only"`
  - `positive_bonus=2.0`
  - `negative_penalty=6.0`
  - `color_bonus=1.5`
  - `budget_penalty=0.5`
  - `budget_tolerance=1.15`
  - `query_coverage_enabled=True`
  - `query_coverage_weight=20.0`
- Validation:
  - Targeted catalog/Agent regression: `68 passed`.
  - Full repository regression: `107 passed`.
  - `git diff --check`: passed.
  - Invalid modes, negative/non-finite weights, an invalid budget tolerance, and a non-boolean coverage flag are rejected by unit tests.
- Command: `python3 -m evaluator.local_evaluator --output /private/tmp/e4_v4_ranking_config_results.json`
- Runtime: approximately 27 seconds for 200 public sessions on the local macOS Python 3.11 environment.
- Network/model usage: none; reported tokens: 0; `SEMANTIC_ENABLED=False`.
- Raw evaluator output: local temporary artifact; not committed.

| Metric | E4 V3 | E4 V4 | Delta |
|---|---:|---:|---:|
| Hit Rate@10 | 0.880000 | 0.880000 | 0.000000 |
| MRR | 0.554861 | 0.554861 | 0.000000 |
| MTTC | 3.330000 | 3.330000 | 0.000000 |
| Efficiency | 0.767000 | 0.767000 | 0.000000 |
| TechnicalScore | **0.759858** | **0.759858** | **0.000000** |

| Scenario | E4 V3 Hit@10 | E4 V4 Hit@10 | E4 V3 MRR | E4 V4 MRR | E4 V3 MTTC | E4 V4 MTTC |
|---|---:|---:|---:|---:|---:|---:|
| Boundary | 1.000000 | 1.000000 | 0.743452 | 0.743452 | 3.200000 | 3.200000 |
| Browsing | 0.937500 | 0.937500 | 0.560813 | 0.560813 | 2.775000 | 2.775000 |
| Buying | 0.925000 | 0.925000 | 0.591682 | 0.591682 | 2.550000 | 2.550000 |
| Intent Override | 0.566667 | 0.566667 | 0.377937 | 0.377937 | 6.933333 | 6.933333 |

Decision: keep E4 V4. The configuration plumbing is behavior-preserving under the default values, while controlled tests prove that individual ranking parameters can be changed or disabled for isolated ablation and immediate rollback.


## Open gates

- Final runtime limits, network policy, model-weight packaging, derived-index packaging, and package-size limits remain unconfirmed.
- These unresolved P2 conditions do not block P0/P1 implementation or the E2 offline evaluation.
