"""Local, offline configuration defaults owned by Engineer D."""
from __future__ import annotations

from dataclasses import dataclass


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


DEFAULT_QUESTION_POLICY_CONFIG = QuestionPolicyConfig()
DEFAULT_RANKING_CONFIG = RankingConfig()

