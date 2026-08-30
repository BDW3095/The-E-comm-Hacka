"""Shared, frozen data structures used across Engineer A/B/C/D modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Candidate:
    """A catalog candidate. Higher ``score`` means more relevant."""

    parent_asin: str
    score: float
    search_text: str
    product: dict[str, Any]
    route_ranks: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedTurn:
    """B's deterministic parse of one user message."""

    positive_slots: dict[str, list[str]] = field(default_factory=dict)
    negative_slots: dict[str, list[str]] = field(default_factory=dict)
    normalized_query: str | None = None
    is_override: bool = False


@dataclass(slots=True)
class SessionState:
    """Per-session state. Only B's state manager may mutate its intent fields."""

    session_id: str
    profile_tags: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    positive_slots: dict[str, list[str]] = field(default_factory=dict)
    negative_slots: dict[str, list[str]] = field(default_factory=dict)
    asked_specific_attributes: set[str] = field(default_factory=set)
    no_preference_attributes: set[str] = field(default_factory=set)
    other_exhausted: bool = False
    intent_epoch: int = 0
    turn: int = 0
    last_query: str = ""
    mode: str = "browsing"

