"""Official Agent adapter scaffold owned by Engineer D.

This file deliberately contains no parser, retrieval, ranking, or semantic
implementation. Those modules are integrated only after their owners merge
their tested APIs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .config import DEFAULT_QUESTION_POLICY_CONFIG
from .types import SessionState


class Agent:
    """Importable official interface until A/B/C modules are integrated."""

    def __init__(self, catalog_path: str | Path = "data/catalog.jsonl") -> None:
        self.catalog_path = Path(catalog_path)
        self.question_policy_config = DEFAULT_QUESTION_POLICY_CONFIG
        self._sessions: dict[str, SessionState] = {}

    def reset(self, session_id: str, user_profile: dict[str, Any]) -> None:
        tags = user_profile.get("preference_tags", [])
        profile_tags = [str(tag) for tag in tags] if isinstance(tags, list) else []
        self._sessions[session_id] = SessionState(
            session_id=session_id,
            profile_tags=profile_tags,
        )

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict[str, Any]:
        if session_id not in self._sessions:
            raise RuntimeError("reset must be called before respond")

        state = self._sessions[session_id]
        state.turn = turn
        state.messages.append(str(user_message))
        ask_attribute = None if turn >= self.question_policy_config.final_turn else "other"
        return {
            "message": "I am still gathering your preferences.",
            "ask_attribute": ask_attribute,
            "recommendations": [],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0},
        }

