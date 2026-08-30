from __future__ import annotations

import pytest

from src.agent import Agent as SourceAgent
from starter.agent import Agent as StarterAgent


def test_starter_reexports_source_agent() -> None:
    assert StarterAgent is SourceAgent


def test_reset_creates_isolated_session_state(tmp_path) -> None:
    agent = StarterAgent(tmp_path / "catalog.jsonl")
    agent.reset("session-a", {"preference_tags": ["comfort"]})
    agent.reset("session-b", {"preference_tags": ["durability"]})

    assert agent._sessions["session-a"].profile_tags == ["comfort"]
    assert agent._sessions["session-b"].profile_tags == ["durability"]


def test_respond_requires_reset(tmp_path) -> None:
    agent = StarterAgent(tmp_path / "catalog.jsonl")
    with pytest.raises(RuntimeError, match="reset must be called"):
        agent.respond("unknown", "I need a jacket", 1, 10)


def test_scaffold_response_is_schema_shaped_and_turn_ten_stops_asking(tmp_path) -> None:
    agent = StarterAgent(tmp_path / "catalog.jsonl")
    agent.reset("session-a", {})

    early = agent.respond("session-a", "I need a jacket", 1, 10)
    final = agent.respond("session-a", "No more preferences", 10, 10)

    assert isinstance(early["message"], str)
    assert early["ask_attribute"] == "other"
    assert early["recommendations"] == []
    assert early["usage"] == {"prompt_tokens": 0, "completion_tokens": 0}
    assert final["ask_attribute"] is None
