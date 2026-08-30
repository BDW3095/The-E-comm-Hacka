from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from analysis.summarize_results import ResultsFormatError, load_summary, render_markdown


def _session(sample: str, scenario: str, rank: int | None, turn: int | None) -> dict:
    return {
        "sample_id": sample,
        "scenario_type": scenario,
        "hit": rank is not None,
        "first_hit_turn": turn,
        "best_rank": rank,
        "reciprocal_rank": 0.0 if rank is None else 1.0 / rank,
    }


def _full_result() -> dict:
    sessions = [
        _session("buy_hit_1", "buying", 1, 2),
        _session("buy_miss", "buying", None, None),
        _session("browse_hit_3", "browsing", 3, 4),
        _session("override_miss", "intent_override", None, None),
    ]
    return {
        "sample_count": 4,
        "hit_rate_at_10": 0.5,
        "mrr": 0.333333,
        "mttc": 7.0,
        "efficiency": 0.4,
        "recommended_technical_score": 0.43,
        "reported_token_usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
        "scenario_metrics": {
            "browsing": {"sample_count": 1, "hit_rate_at_10": 1.0, "mrr": 0.333333, "mttc": 4.0},
            "buying": {"sample_count": 2, "hit_rate_at_10": 0.5, "mrr": 0.5, "mttc": 6.5},
            "intent_override": {"sample_count": 1, "hit_rate_at_10": 0.0, "mrr": 0.0, "mttc": 11.0},
        },
        "sessions": sessions,
    }


class AnalysisTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_directory.name)

    def tearDown(self) -> None:
        self.temp_directory.cleanup()

    def write(self, name: str, payload: dict) -> Path:
        path = self.root / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_reads_official_full_results_and_groups_diagnostics(self) -> None:
        run = load_summary(self.write("results.json", _full_result()), "E1")

        self.assertEqual(run.overall.sample_count, 4)
        self.assertEqual(
            run.rank_distribution,
            {"1": 1, "2-3": 1, "4-5": 0, "6-10": 0, "miss": 2},
        )
        self.assertEqual(run.miss_counts, {"buying": 1, "intent_override": 1})
        self.assertEqual(run.failure_ids["buying"], ("buy_miss",))

    def test_reads_aggregate_only_baseline_and_technical_score_alias(self) -> None:
        payload = {
            "sample_count": 200,
            "hit_rate_at_10": 0.125,
            "mrr": 0.068034,
            "mttc": 9.81,
            "efficiency": 0.119,
            "technical_score": 0.10671,
        }
        run = load_summary(self.write("baseline.json", payload), "E0")

        self.assertAlmostEqual(run.technical_score, 0.10671)
        self.assertEqual(run.scenario_metrics, {})
        self.assertEqual(sum(run.rank_distribution.values()), 0)

    def test_empty_results_are_supported(self) -> None:
        payload = {
            "sample_count": 0,
            "hit_rate_at_10": 0.0,
            "mrr": 0.0,
            "mttc": None,
            "efficiency": 0.0,
            "recommended_technical_score": 0.0,
            "scenario_metrics": {},
            "sessions": [],
        }
        run = load_summary(self.write("empty.json", payload), "empty")

        self.assertIsNone(run.overall.mttc)
        self.assertIn("| empty | 0 |", render_markdown([run]))

    def test_markdown_is_stable_and_compares_against_first_run(self) -> None:
        baseline_payload = _full_result()
        candidate_payload = _full_result()
        candidate_payload["recommended_technical_score"] = 0.45
        candidate_payload["hit_rate_at_10"] = 0.55
        e0 = load_summary(self.write("e0.json", baseline_payload), "E0")
        e1 = load_summary(self.write("e1.json", candidate_payload), "E1")

        first = render_markdown([e0, e1])
        second = render_markdown([e0, e1])

        self.assertEqual(first, second)
        self.assertIn("| E1 | 4 | 0.550000", first)
        self.assertIn("**0.450000** | +0.020000", first)
        self.assertIn("hidden (use --include-failure-ids)", first)
        self.assertNotIn("buy_miss", first)

    def test_failure_ids_require_explicit_opt_in(self) -> None:
        run = load_summary(self.write("results.json", _full_result()), "E1")

        markdown = render_markdown([run], include_failure_ids=True)

        self.assertIn("buy_miss", markdown)
        self.assertIn("override_miss", markdown)

    def test_rejects_inconsistent_miss(self) -> None:
        payload = _full_result()
        payload["sessions"][1]["best_rank"] = 5

        with self.assertRaisesRegex(ResultsFormatError, "miss fields are inconsistent"):
            load_summary(self.write("bad.json", payload), "bad")

    def test_rejects_session_count_mismatch(self) -> None:
        payload = _full_result()
        payload["sample_count"] = 99

        with self.assertRaisesRegex(ResultsFormatError, "sample_count disagrees"):
            load_summary(self.write("bad.json", payload), "bad")


if __name__ == "__main__":
    unittest.main()
