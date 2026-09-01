# The-E-comm-Hacka

Offline-first conversational shopping agent for the TechJam Conversational E-Commerce Search Challenge.

The current P0/P1 submission pipeline is:

```text
StateManager
→ SQLite FTS5 Lexical Top-200
→ ConstraintRanker
→ Top-10 RecommendationValidator
→ QuestionPolicy
→ official response
```

It is deterministic, uses no network or API key, and keeps `SEMANTIC_ENABLED=False`.
`P2-Dense` / RRF is future work only because its runtime and packaging limits are still unconfirmed.

## Local development setup

Download the official participant kit, verify its SHA256 checksum, and unpack its `data/` and `evaluator/` directories at the repository root. These official development artifacts are intentionally ignored by Git.

The verified participant-kit SHA256 used for the E0 baseline is:

```text
b3d7e283b835343b42c4919ea2ca90f2fb5a2aa2b10537f14dcf42f03e5b38ae
```

Use Python 3.11 and create an isolated development environment:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Run the repository regressions:

```bash
python -m pytest -q
```

Run the official local evaluator:

```bash
python -m evaluator.local_evaluator --output artifacts/local_results.json
```

The verified unmodified official starter baseline is E0, with `TechnicalScore = 0.106710`.
The current E5 release candidate has `TechnicalScore = 0.759858` on the released local evaluator.
See [docs/experiment_log.md](docs/experiment_log.md) for environment checks, configs, runtime, and scenario metrics.

## Method and model choice

Muse is an offline-first conversational shopping Agent. It uses `SQLite FTS5`
lexical retrieval to obtain a Top-200 candidate set, then applies a
`ConstraintRanker` using accumulated conversation preferences. `StateManager`
handles incremental preference accumulation and `Intent Override`;
`QuestionPolicy` uses the released evaluator-compatible
`other-until-exhausted` strategy.

The submission does not use an external `LLM`, external API, Dense Retrieval,
or model weights. `SEMANTIC_ENABLED=False`.

## Runtime, token usage, and cost

On the released local evaluator, the 200-session E5 evaluation completed in
approximately 33.217 seconds on local macOS / Python 3.11 development
hardware. The Agent reports `0` prompt tokens and `0` completion tokens, uses
no network connection, and has an estimated external model/API cost of `$0`.

## Limitations and future improvements

- The current system is optimized and validated against the released
  template-based evaluator; more diverse natural-language paraphrases may
  require a stronger semantic parser.
- `Intent Override` remains the weakest released scenario and is the main
  source of remaining retrieval misses.
- The current P0/P1 pipeline is lexical. `P2-Dense + RRF` is future work and
  should only be evaluated after runtime, package-size, and model-weight
  constraints are confirmed.
- Because one `parent_asin` can represent multiple SKU variants, color uses
  `positive-evidence-only`: an explicit matching color adds evidence, while a
  non-matching color is not treated as a hard conflict.

## Team contributions

- ZHU YIHAN: catalog indexing, `SQLite FTS5` retrieval,
  `ConstraintRanker`, and recommendation validation.
- DUAN YUGUANG: conversation state, intent parsing, `Intent Override`,
  and `QuestionPolicy`.
- WEN BIDONG: evaluator analysis, regression comparison, and
  experiment validation.
- WANG CHEN: shared contracts, Agent integration, fallback
  reliability, release readiness, and submission documentation.

## Repository layout

- `starter/agent.py` is the only official entrypoint and re-exports `src.agent.Agent`.
- `src/` is the production package: catalog/FTS5 retrieval, conversation state, policy, ranking, and Agent assembly.
- `tests/` contains deterministic unit and E2E regression tests without public labels.
- `analysis/` reads evaluator outputs after a run; it is never imported by production Agent code.
- `docs/` contains the current plan, organizer Q&A, experiment log, and official references.

## Runtime and fallback behavior

`Agent` fails fast if its catalog file is missing or has fewer than 10 unique `parent_asin` values. Once initialized, empty retrieval or a runtime retriever/ranker failure falls back to a stable catalog order, so the official response still contains 10 unique catalog-valid recommendations.

Every turn returns recommendations. Turn 10 only changes `ask_attribute` to `null`; it does not remove the Top-10 output.

## Demo walkthrough

1. Place the verified official `data/` and `evaluator/` folders at repository root.
2. Run the test suite.
3. Run `python -m evaluator.local_evaluator`.
4. Inspect the ignored output with:

```bash
python analysis/summarize_results.py E5=artifacts/local_results.json
```

The production Agent must remain offline-capable. Do not commit official data, evaluator outputs, model weights, embedding indexes, API keys, secrets, or public-label-derived artifacts.
