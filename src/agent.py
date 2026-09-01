"""Official Agent adapter assembling the team's deterministic E1 pipeline."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .catalog import CatalogIndex
from .config import (
    DEFAULT_QUESTION_POLICY_CONFIG,
    DEFAULT_RANKING_CONFIG,
    RETRIEVAL_LIMIT,
    RankingConfig,
)
from .policy import QuestionPolicy
from .retrieval import ConstraintRanker, LexicalRetriever, validate_recommendations
from .state import StateManager
from .types import Candidate, SessionState


class Agent:
    """Offline shopping agent used by the official evaluator.

    Call order is intentionally explicit and owner-aligned:
    B state update -> A lexical retrieval -> A constraint rerank ->
    B question policy -> D response validation/assembly.
    """

    def __init__(
        self,
        catalog_path: str | Path = "data/catalog.jsonl",
        ranking_config: RankingConfig | None = None,
    ) -> None:
        self.catalog_path = Path(catalog_path)
        self.question_policy_config = DEFAULT_QUESTION_POLICY_CONFIG
        self.ranking_config = ranking_config or DEFAULT_RANKING_CONFIG
        self._state_manager = StateManager()
        # Preserve the shared session mapping expected by integration tests.
        self._sessions: dict[str, SessionState] = self._state_manager._states
        self._question_policy = QuestionPolicy(self.question_policy_config)

        self._catalog: CatalogIndex | None = None
        self._retriever: LexicalRetriever | None = None
        self._ranker: ConstraintRanker | None = None
        if self.catalog_path.is_file():
            self._catalog = CatalogIndex(self.catalog_path)
            self._retriever = LexicalRetriever(self._catalog)
            self._ranker = ConstraintRanker(
                self._catalog,
                ranking_config=self.ranking_config,
            )

    def reset(self, session_id: str, user_profile: dict[str, Any]) -> None:
        self._state_manager.reset(session_id, user_profile)

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict[str, Any]:
        state = self._state_manager.update(session_id, str(user_message), int(turn))
        candidates = self._retrieve_and_rank(state)

        if self._catalog is None:
            recommendations: list[dict[str, Any]] = []
        else:
            recommendations = validate_recommendations(
                candidates,
                valid_ids=self._catalog.valid_ids,
                fallback_ids=self._catalog.stable_fallback_ids(),
                top_k=int(top_k),
            )

        ask_attribute = self._question_policy.choose_attribute(state, candidates, int(turn))
        return {
            "message": self._question_policy.render_message(ask_attribute),
            "ask_attribute": ask_attribute,
            "recommendations": recommendations,
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }

    def _retrieve_and_rank(self, state: SessionState) -> list[Candidate]:
        if self._retriever is None or self._ranker is None:
            return []
        candidates = self._retriever.retrieve(state.last_query, limit=RETRIEVAL_LIMIT)
        return self._ranker.rerank(candidates, state)
