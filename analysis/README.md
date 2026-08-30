# Offline Evaluator Test and Analysis Script

`summarize_results.py` is Engineer C's offline testing and experiment-analysis
tool. It reads evaluator-generated `results.json` files after a run and produces
deterministic Markdown summaries and E0/E1/E2/E3 comparisons.

This directory is **not production Agent code**:

- it must never be imported by `src/` or `starter/`;
- it does not modify evaluator results;
- it does not feed public session IDs or labels back into ranking logic;
- raw `results.json` files and failure-ID output must not be committed.

Example:

```bash
python3 analysis/summarize_results.py \
  E0=/path/to/e0_results.json \
  E1=/path/to/e1_results.json \
  E2=/path/to/e2_results.json \
  --output analysis_summary.md
```

Failure IDs are hidden by default. For temporary local diagnosis only:

```bash
python3 analysis/summarize_results.py \
  E2=/path/to/results.json \
  --include-failure-ids
```

Run its tests with:

```bash
pytest tests/test_analysis.py -q
```
