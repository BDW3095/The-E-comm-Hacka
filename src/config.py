"""Local, offline configuration defaults owned by Engineer D."""
from __future__ import annotations

from dataclasses import dataclass
import math


ALLOWED_ASK_ATTRIBUTES = frozenset({
    "category", "material", "color", "size", "style", "brand",
    "budget", "feature", "use_case", "other",
})
ASKABLE_ATTRIBUTES = (
    "material", "color", "size", "style", "feature", "use_case", "budget", "other",
)
SLOT_KEYS = (
    "category", "material", "color", "size", "style", "brand", "budget", "feature", "use_case",
)
RETRIEVAL_LIMIT = 200
SEMANTIC_ENABLED = False


@dataclass(frozen=True, slots=True)
class QuestionPolicyConfig:
    mode: str = "simulator_optimized"
    final_turn: int = 10
    askable_attributes: tuple[str, ...] = ASKABLE_ATTRIBUTES


@dataclass(frozen=True, slots=True)
class RankingConfig:
    color_conflict_mode: str = "positive_evidence_only"
    positive_bonus: float = 2.0
    negative_penalty: float = 6.0
    color_bonus: float = 1.5
    budget_penalty: float = 0.5
    budget_tolerance: float = 1.15
    query_coverage_enabled: bool = True
    query_coverage_weight: float = 20.0

    def __post_init__(self) -> None:
        if self.color_conflict_mode != "positive_evidence_only":
            raise ValueError(
                "color_conflict_mode must be 'positive_evidence_only'"
            )
        if not isinstance(self.query_coverage_enabled, bool):
            raise TypeError("query_coverage_enabled must be a bool")

        nonnegative_fields = (
            "positive_bonus",
            "negative_penalty",
            "color_bonus",
            "budget_penalty",
            "query_coverage_weight",
        )
        for field_name in nonnegative_fields:
            value = getattr(self, field_name)
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                raise ValueError(f"{field_name} must be a finite non-negative number")

        tolerance = self.budget_tolerance
        if (
            isinstance(tolerance, bool)
            or not isinstance(tolerance, (int, float))
            or not math.isfinite(tolerance)
            or tolerance < 1.0
        ):
            raise ValueError("budget_tolerance must be a finite number >= 1.0")


DEFAULT_QUESTION_POLICY_CONFIG = QuestionPolicyConfig()
DEFAULT_RANKING_CONFIG = RankingConfig()
