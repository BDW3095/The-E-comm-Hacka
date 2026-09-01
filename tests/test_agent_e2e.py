from __future__ import annotations

import pytest

from src.agent import Agent as SourceAgent
from src.config import RankingConfig
from src.types import Candidate
from starter.agent import Agent as StarterAgent


def _write_catalog(path, item_count: int = 12) -> None:
    import json

    rows = []
    for index in range(item_count):
        rows.append(
            {
                "parent_asin": f"A{index:04d}",
                "title": "Black cotton running shoes" if index == 0 else f"Fallback item {index}",
                "features": ["breathable"] if index == 0 else [],
                "categories": ["Shoes"],
                "details": {"Color": "Black", "Material": "Cotton"} if index == 0 else {},
                "average_rating": 5.0 - index / 20,
                "rating_number": 100 - index,
                "price": 40 + index,
            }
        )
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_starter_reexports_source_agent() -> None:
    assert StarterAgent is SourceAgent


def test_agent_injects_custom_ranking_config(tmp_path) -> None:
    catalog_path = tmp_path / "catalog.jsonl"
    _write_catalog(catalog_path)
    ranking_config = RankingConfig(
        query_coverage_enabled=False,
        negative_penalty=3.0,
    )

    agent = StarterAgent(catalog_path, ranking_config=ranking_config)

    assert agent.ranking_config is ranking_config
    assert agent._ranker is not None
    assert agent._ranker._config is ranking_config


def test_official_single_argument_constructor_uses_default_ranking_config(tmp_path) -> None:
    catalog_path = tmp_path / "catalog.jsonl"
    _write_catalog(catalog_path)

    agent = StarterAgent(catalog_path)

    assert agent.ranking_config == RankingConfig()


def test_reset_creates_isolated_session_state(tmp_path) -> None:
    catalog_path = tmp_path / "catalog.jsonl"
    _write_catalog(catalog_path)
    agent = StarterAgent(catalog_path)
    agent.reset("session-a", {"preference_tags": ["comfort"]})
    agent.reset("session-b", {"preference_tags": ["durability"]})

    assert agent._sessions["session-a"].profile_tags == ["comfort"]
    assert agent._sessions["session-b"].profile_tags == ["durability"]


def test_respond_requires_reset(tmp_path) -> None:
    catalog_path = tmp_path / "catalog.jsonl"
    _write_catalog(catalog_path)
    agent = StarterAgent(catalog_path)
    with pytest.raises(RuntimeError, match="reset must be called"):
        agent.respond("unknown", "I need a jacket", 1, 10)


def test_response_is_schema_valid_and_turn_ten_stops_asking(tmp_path) -> None:
    catalog_path = tmp_path / "catalog.jsonl"
    _write_catalog(catalog_path)
    agent = StarterAgent(catalog_path)
    agent.reset("session-a", {})

    early = agent.respond("session-a", "I need a jacket", 1, 10)
    final = agent.respond("session-a", "No more preferences", 10, 10)

    assert isinstance(early["message"], str)
    assert early["ask_attribute"] == "other"
    assert len(early["recommendations"]) == 10
    assert len({item["parent_asin"] for item in early["recommendations"]}) == 10
    assert early["usage"] == {"prompt_tokens": 0, "completion_tokens": 0}
    assert final["ask_attribute"] is None
    assert len(final["recommendations"]) == 10


def test_missing_catalog_fails_fast(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="catalog file not found"):
        StarterAgent(tmp_path / "missing.jsonl")


def test_catalog_with_fewer_than_ten_unique_ids_fails_fast(tmp_path) -> None:
    catalog_path = tmp_path / "catalog.jsonl"
    _write_catalog(catalog_path, item_count=9)

    with pytest.raises(RuntimeError, match="requires at least 10 unique"):
        StarterAgent(catalog_path)


def test_empty_query_uses_valid_stable_fallback(tmp_path) -> None:
    catalog_path = tmp_path / "catalog.jsonl"
    _write_catalog(catalog_path)
    agent = StarterAgent(catalog_path)
    agent.reset("session-a", {})

    response = agent.respond("session-a", "", 1, 10)

    assert len(response["recommendations"]) == 10
    assert len({item["parent_asin"] for item in response["recommendations"]}) == 10


@pytest.mark.parametrize("failed_component", ("_retriever", "_ranker"))
def test_runtime_retrieval_or_ranking_failure_uses_top_ten_fallback(
    tmp_path, monkeypatch, failed_component
) -> None:
    catalog_path = tmp_path / "catalog.jsonl"
    _write_catalog(catalog_path)
    agent = StarterAgent(catalog_path)
    agent.reset("session-a", {})

    def raise_runtime_error(*_args, **_kwargs):
        raise RuntimeError("simulated component failure")

    component = getattr(agent, failed_component)
    assert component is not None
    method_name = "retrieve" if failed_component == "_retriever" else "rerank"
    monkeypatch.setattr(component, method_name, raise_runtime_error)

    response = agent.respond("session-a", "I need running shoes", 1, 10)

    assert response["ask_attribute"] == "other"
    assert len(response["recommendations"]) == 10
    assert len({item["parent_asin"] for item in response["recommendations"]}) == 10


def test_invalid_and_duplicate_candidates_are_cleaned_by_agent_validation(tmp_path, monkeypatch) -> None:
    catalog_path = tmp_path / "catalog.jsonl"
    _write_catalog(catalog_path)
    agent = StarterAgent(catalog_path)
    agent.reset("session-a", {})

    monkeypatch.setattr(
        agent,
        "_retrieve_and_rank",
        lambda _state: [
            Candidate("NOT_IN_CATALOG", 100.0, "", {}),
            Candidate("A0001", 2.0, "", {}),
            Candidate("A0001", 1.0, "", {}),
        ],
    )

    response = agent.respond("session-a", "I need shoes", 1, 10)
    asins = [item["parent_asin"] for item in response["recommendations"]]

    assert len(asins) == 10
    assert len(set(asins)) == 10
    assert "NOT_IN_CATALOG" not in asins


def test_integrated_agent_returns_ranked_valid_top_ten(tmp_path) -> None:
    catalog_path = tmp_path / "catalog.jsonl"
    _write_catalog(catalog_path)
    agent = StarterAgent(catalog_path)
    agent.reset("session-a", {})

    response = agent.respond(
        "session-a",
        "I need black cotton running shoes under $50",
        1,
        10,
    )

    recommendations = response["recommendations"]
    assert len(recommendations) == 10
    assert len({item["parent_asin"] for item in recommendations}) == 10
    assert recommendations[0]["parent_asin"] == "A0000"
    assert response["ask_attribute"] == "other"
    assert agent._sessions["session-a"].positive_slots["color"] == ["black"]
    assert agent._sessions["session-a"].positive_slots["budget"] == ["max:50"]


def test_integrated_agent_accumulates_constraints_across_turns(tmp_path) -> None:
    catalog_path = tmp_path / "catalog.jsonl"
    _write_catalog(catalog_path)
    agent = StarterAgent(catalog_path)
    agent.reset("session-a", {})

    agent.respond("session-a", "I need running shoes", 1, 10)
    response = agent.respond("session-a", "For that, black cotton matters.", 2, 10)

    state = agent._sessions["session-a"]
    assert state.positive_slots["category"] == ["shoes"]
    assert state.positive_slots["color"] == ["black"]
    assert state.positive_slots["material"] == ["cotton"]
    assert response["recommendations"][0]["parent_asin"] == "A0000"
