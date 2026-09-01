#!/usr/bin/env python3
"""Offline, deterministic summaries for TechJam evaluator ``results.json`` files.

This module deliberately does not import ``src`` or the evaluator.  It only reads
the JSON files supplied on the command line and emits Markdown suitable for the
append-only experiment log.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from typing import Any, Iterable


MAX_TURNS = 10
SCENARIO_ORDER = ("boundary", "browsing", "buying", "intent_override")
SCENARIO_NAMES = {
    "boundary": "Boundary",
    "browsing": "Browsing",
    "buying": "Buying",
    "intent_override": "Intent Override",
}


class ResultsFormatError(ValueError):
    """Raised when an input is not an official evaluator-compatible result."""


@dataclass(frozen=True)
class Metrics:
    sample_count: int
    hit_rate_at_10: float
    mrr: float
    mttc: float | None


@dataclass(frozen=True)
class RunSummary:
    label: str
    source: Path
    overall: Metrics
    efficiency: float
    technical_score: float
    scenario_metrics: dict[str, Metrics]
    rank_distribution: dict[str, int]
    miss_counts: dict[str, int]
    failure_ids: dict[str, tuple[str, ...]]
    token_usage: dict[str, int]


def _as_number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResultsFormatError(f"{field} must be a number")
    return float(value)


def _as_nonnegative_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResultsFormatError(f"{field} must be a non-negative integer")
    return value


def _metrics_from_mapping(payload: dict[str, Any], prefix: str) -> Metrics:
    count = _as_nonnegative_int(payload.get("sample_count"), f"{prefix}.sample_count")
    hit_rate = _as_number(payload.get("hit_rate_at_10"), f"{prefix}.hit_rate_at_10")
    mrr = _as_number(payload.get("mrr"), f"{prefix}.mrr")
    raw_mttc = payload.get("mttc")
    mttc = None if raw_mttc is None else _as_number(raw_mttc, f"{prefix}.mttc")
    if not 0.0 <= hit_rate <= 1.0:
        raise ResultsFormatError(f"{prefix}.hit_rate_at_10 must be in [0, 1]")
    if not 0.0 <= mrr <= 1.0:
        raise ResultsFormatError(f"{prefix}.mrr must be in [0, 1]")
    return Metrics(count, hit_rate, mrr, mttc)


def _metrics_from_sessions(sessions: list[dict[str, Any]]) -> Metrics:
    if not sessions:
        return Metrics(0, 0.0, 0.0, None)
    count = len(sessions)
    hits = sum(1 for session in sessions if session["hit"])
    reciprocal_rank = sum(float(session["reciprocal_rank"]) for session in sessions)
    turns = [
        int(session["first_hit_turn"])
        if session["first_hit_turn"] is not None
        else MAX_TURNS + 1
        for session in sessions
    ]
    return Metrics(count, hits / count, reciprocal_rank / count, sum(turns) / count)


def _validate_sessions(raw: Any) -> list[dict[str, Any]]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ResultsFormatError("sessions must be a list")
    validated: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        prefix = f"sessions[{index}]"
        if not isinstance(item, dict):
            raise ResultsFormatError(f"{prefix} must be an object")
        scenario = item.get("scenario_type")
        if not isinstance(scenario, str) or not scenario:
            raise ResultsFormatError(f"{prefix}.scenario_type must be a non-empty string")
        hit = item.get("hit")
        if not isinstance(hit, bool):
            raise ResultsFormatError(f"{prefix}.hit must be a boolean")
        sample_id = item.get("sample_id")
        if not isinstance(sample_id, str) or not sample_id:
            raise ResultsFormatError(f"{prefix}.sample_id must be a non-empty string")
        first_hit_turn = item.get("first_hit_turn")
        best_rank = item.get("best_rank")
        reciprocal_rank = _as_number(item.get("reciprocal_rank"), f"{prefix}.reciprocal_rank")
        if hit:
            if not isinstance(first_hit_turn, int) or not 1 <= first_hit_turn <= MAX_TURNS:
                raise ResultsFormatError(f"{prefix}.first_hit_turn is invalid for a hit")
            if not isinstance(best_rank, int) or not 1 <= best_rank <= 10:
                raise ResultsFormatError(f"{prefix}.best_rank is invalid for a hit")
            if abs(reciprocal_rank - 1.0 / best_rank) > 1e-6:
                raise ResultsFormatError(f"{prefix}.reciprocal_rank disagrees with best_rank")
        elif first_hit_turn is not None or best_rank is not None or reciprocal_rank != 0.0:
            raise ResultsFormatError(f"{prefix} miss fields are inconsistent")
        validated.append(item)
    return validated


def _scenario_sort_key(name: str) -> tuple[int, str]:
    try:
        return (SCENARIO_ORDER.index(name), name)
    except ValueError:
        return (len(SCENARIO_ORDER), name)


def _score(payload: dict[str, Any], overall: Metrics, efficiency: float) -> float:
    raw = payload.get("recommended_technical_score", payload.get("technical_score"))
    if raw is not None:
        return _as_number(raw, "technical_score")
    return 0.50 * overall.hit_rate_at_10 + 0.30 * overall.mrr + 0.20 * efficiency


def summarize_payload(payload: dict[str, Any], label: str, source: Path) -> RunSummary:
    """Validate one official-style payload and return normalized summary data."""
    if not isinstance(payload, dict):
        raise ResultsFormatError("top-level JSON must be an object")
    overall = _metrics_from_mapping(payload, "overall")
    efficiency = _as_number(payload.get("efficiency"), "efficiency")
    if not 0.0 <= efficiency <= 1.0:
        raise ResultsFormatError("efficiency must be in [0, 1]")

    scenario_raw = payload.get("scenario_metrics", {})
    if not isinstance(scenario_raw, dict):
        raise ResultsFormatError("scenario_metrics must be an object")
    scenario_metrics = {
        name: _metrics_from_mapping(value, f"scenario_metrics.{name}")
        for name, value in scenario_raw.items()
        if isinstance(name, str) and isinstance(value, dict)
    }

    sessions = _validate_sessions(payload.get("sessions"))
    rank_distribution = {"1": 0, "2-3": 0, "4-5": 0, "6-10": 0, "miss": 0}
    miss_counts: Counter[str] = Counter()
    failure_ids: defaultdict[str, list[str]] = defaultdict(list)
    if sessions:
        derived = _metrics_from_sessions(sessions)
        if derived.sample_count != overall.sample_count:
            raise ResultsFormatError("overall.sample_count disagrees with sessions")
        grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
        for session in sessions:
            scenario = session["scenario_type"]
            grouped[scenario].append(session)
            rank = session["best_rank"]
            if rank is None:
                rank_distribution["miss"] += 1
                miss_counts[scenario] += 1
                failure_ids[scenario].append(session["sample_id"])
            elif rank == 1:
                rank_distribution["1"] += 1
            elif rank <= 3:
                rank_distribution["2-3"] += 1
            elif rank <= 5:
                rank_distribution["4-5"] += 1
            else:
                rank_distribution["6-10"] += 1
        for scenario, items in grouped.items():
            derived_scenario = _metrics_from_sessions(items)
            existing = scenario_metrics.get(scenario)
            if existing and existing.sample_count != derived_scenario.sample_count:
                raise ResultsFormatError(
                    f"scenario_metrics.{scenario}.sample_count disagrees with sessions"
                )
            scenario_metrics.setdefault(scenario, derived_scenario)

    usage_raw = payload.get("reported_token_usage", {})
    if not isinstance(usage_raw, dict):
        raise ResultsFormatError("reported_token_usage must be an object")
    token_usage = {
        key: _as_nonnegative_int(usage_raw.get(key, 0), f"reported_token_usage.{key}")
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    return RunSummary(
        label=label,
        source=source,
        overall=overall,
        efficiency=efficiency,
        technical_score=_score(payload, overall, efficiency),
        scenario_metrics=dict(sorted(scenario_metrics.items(), key=lambda item: _scenario_sort_key(item[0]))),
        rank_distribution=rank_distribution,
        miss_counts=dict(miss_counts),
        failure_ids={key: tuple(sorted(values)) for key, values in failure_ids.items()},
        token_usage=token_usage,
    )


def load_summary(path: Path, label: str | None = None) -> RunSummary:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise ResultsFormatError(f"cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ResultsFormatError(f"invalid JSON in {path}: {exc}") from exc
    return summarize_payload(payload, label or path.stem, path)


def _fmt(value: float | None, signed: bool = False) -> str:
    if value is None:
        return "N/A"
    return f"{value:+.6f}" if signed else f"{value:.6f}"


def render_markdown(
    runs: Iterable[RunSummary], *, include_failure_ids: bool = False, max_failure_ids: int = 20
) -> str:
    """Render deterministic Markdown; the first run is the comparison baseline."""
    rows = list(runs)
    if not rows:
        raise ValueError("at least one run is required")
    baseline = rows[0]
    out = ["## Evaluator Results Summary", "", "### Overall", ""]
    out.append(
        "| Run | Samples | Hit@10 | MRR | MTTC | Efficiency | TechnicalScore | Delta Score |"
    )
    out.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for run in rows:
        delta = run.technical_score - baseline.technical_score
        out.append(
            f"| {run.label} | {run.overall.sample_count} | "
            f"{_fmt(run.overall.hit_rate_at_10)} | {_fmt(run.overall.mrr)} | "
            f"{_fmt(run.overall.mttc)} | {_fmt(run.efficiency)} | "
            f"**{_fmt(run.technical_score)}** | {_fmt(delta, signed=True)} |"
        )

    all_scenarios = sorted(
        {name for run in rows for name in run.scenario_metrics}, key=_scenario_sort_key
    )
    out.extend(["", "### Per-scenario metrics", ""])
    out.append("| Run | Scenario | Samples | Hit@10 | Delta Hit | MRR | Delta MRR | MTTC | Delta MTTC |")
    out.append("|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for run in rows:
        for scenario in all_scenarios:
            current = run.scenario_metrics.get(scenario)
            if current is None:
                continue
            base = baseline.scenario_metrics.get(scenario)
            delta_hit = current.hit_rate_at_10 - base.hit_rate_at_10 if base else None
            delta_mrr = current.mrr - base.mrr if base else None
            delta_mttc = (
                current.mttc - base.mttc
                if base and current.mttc is not None and base.mttc is not None
                else None
            )
            out.append(
                f"| {run.label} | {SCENARIO_NAMES.get(scenario, scenario)} | "
                f"{current.sample_count} | {_fmt(current.hit_rate_at_10)} | "
                f"{_fmt(delta_hit, signed=True)} | {_fmt(current.mrr)} | "
                f"{_fmt(delta_mrr, signed=True)} | {_fmt(current.mttc)} | "
                f"{_fmt(delta_mttc, signed=True)} |"
            )

    session_runs = [run for run in rows if sum(run.rank_distribution.values())]
    if session_runs:
        out.extend(["", "### Rank and miss diagnostics", ""])
        out.append("| Run | Rank 1 | Rank 2-3 | Rank 4-5 | Rank 6-10 | Miss |")
        out.append("|---|---:|---:|---:|---:|---:|")
        for run in session_runs:
            rank = run.rank_distribution
            out.append(
                f"| {run.label} | {rank['1']} | {rank['2-3']} | {rank['4-5']} | "
                f"{rank['6-10']} | {rank['miss']} |"
            )
        out.extend(["", "| Run | Scenario | Misses | Failure IDs |", "|---|---|---:|---|"])
        for run in session_runs:
            for scenario in sorted(run.miss_counts, key=_scenario_sort_key):
                ids = run.failure_ids.get(scenario, ())
                if include_failure_ids:
                    shown = list(ids[:max_failure_ids])
                    failure_text = ", ".join(shown)
                    if len(ids) > len(shown):
                        failure_text += f" ... (+{len(ids) - len(shown)} more)"
                else:
                    failure_text = "hidden (use --include-failure-ids)"
                out.append(
                    f"| {run.label} | {SCENARIO_NAMES.get(scenario, scenario)} | "
                    f"{run.miss_counts[scenario]} | {failure_text} |"
                )

    out.extend(["", "### Source files", ""])
    for run in rows:
        out.append(f"- `{run.label}`: `{run.source}`")
    out.extend([
        "",
        "> Offline analysis only. Do not import this module from production Agent code or copy public session labels into ranking logic.",
    ])
    return "\n".join(out) + "\n"


def _parse_run(value: str) -> tuple[str | None, Path]:
    if "=" in value:
        label, path = value.split("=", 1)
        if not label.strip() or not path.strip():
            raise argparse.ArgumentTypeError("run must be LABEL=PATH or PATH")
        return label.strip(), Path(path)
    return None, Path(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Summarize and compare TechJam evaluator results as Markdown."
    )
    parser.add_argument(
        "runs", nargs="+", type=_parse_run, metavar="[LABEL=]RESULTS_JSON",
        help="first run is the baseline for all deltas",
    )
    parser.add_argument("--output", type=Path, help="write Markdown to this path instead of stdout")
    parser.add_argument(
        "--include-failure-ids", action="store_true",
        help="include public sample IDs for local diagnosis; do not commit that output",
    )
    parser.add_argument("--max-failure-ids", type=int, default=20)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.max_failure_ids < 0:
        parser.error("--max-failure-ids must be non-negative")
    try:
        summaries = [load_summary(path, label) for label, path in args.runs]
        markdown = render_markdown(
            summaries,
            include_failure_ids=args.include_failure_ids,
            max_failure_ids=args.max_failure_ids,
        )
        if args.output:
            args.output.write_text(markdown, encoding="utf-8")
        else:
            sys.stdout.write(markdown)
    except (ResultsFormatError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
