"""Regression tests for Part B's deterministic state and question policy."""

from __future__ import annotations

from src.policy import OFFICIAL_ATTRIBUTES, QuestionPolicy, QuestionPolicyConfig
from src.state import LocalParser, StateManager, is_strong_override
from src.types import Candidate


def _profile() -> dict:
    return {
        "purchase_frequency": "3-4 prior purchases",
        "average_prior_rating": 5.0,
        "rating_style": "usually positive",
        "preference_tags": ["comfort", "durability"],
        "summary": "Prior purchases emphasize fit and comfort.",
    }


def _manager_with_state(session_id: str = "session-a") -> tuple[StateManager, object]:
    manager = StateManager()
    manager.reset(session_id, _profile())
    return manager, manager.get_state(session_id)


def test_parser_extracts_positive_negative_and_structured_budget() -> None:
    parser = LocalParser()

    parsed = parser.parse("I need a black cotton shirt for hiking under $40, not a slim fit.")

    assert parsed.positive_slots["color"] == ["black"]
    assert parsed.positive_slots["material"] == ["cotton"]
    assert parsed.positive_slots["use_case"] == ["hiking"]
    assert parsed.positive_slots["budget"] == ["max:40"]
    assert parsed.negative_slots["style"] == ["slim fit"]
    assert "slim fit" not in (parsed.normalized_query or "")


def test_parser_keeps_minimum_and_target_budget_meanings_distinct() -> None:
    parser = LocalParser()

    parsed = parser.parse("I need something over $25 and around $50.")

    assert parsed.positive_slots["budget"] == ["min:25", "target:50"]


def test_parser_matches_a_catalog_vocabulary_and_hyphenated_features() -> None:
    parser = LocalParser()

    parsed = parser.parse(
        "A navy cashmere XXXL vintage jacket for summer, with water-resistant fabric."
    )

    assert parsed.positive_slots["color"] == ["navy"]
    assert parsed.positive_slots["material"] == ["cashmere"]
    assert parsed.positive_slots["size"] == ["xxxl"]
    assert parsed.positive_slots["style"] == ["vintage"]
    assert parsed.positive_slots["use_case"] == ["summer"]
    assert parsed.positive_slots["feature"] == ["water resistant"]


def test_parser_recognises_single_letter_sizes_only_with_explicit_context() -> None:
    parser = LocalParser()

    assert parser.parse("I prefer an M size green shirt.").positive_slots["size"] == ["medium"]
    assert parser.parse("Size: M.").positive_slots["size"] == ["medium"]
    assert parser.parse("Size = L.").positive_slots["size"] == ["large"]
    assert parser.parse("An M-sized jacket.").positive_slots["size"] == ["medium"]


def test_parser_rejects_ambiguous_single_letter_sizes() -> None:
    parser = LocalParser()

    for message in (
        "I'm looking for shirts.",
        "I'm looking for men's shirts.",
        "I'm looking for women's shoes.",
        "Water resistance: 30 M.",
        "Model: ABC-123-M.",
        "S/M/L available.",
        "M/L size chart.",
    ):
        assert "size" not in parser.parse(message).positive_slots


def test_parser_places_explicit_negative_single_letter_size_in_negative_slots() -> None:
    parsed = LocalParser().parse("I do not want an M size shirt.")

    assert parsed.negative_slots["size"] == ["medium"]
    assert "size" not in parsed.positive_slots


def test_parser_requires_context_for_regular_wide_and_narrow_size_values() -> None:
    parser = LocalParser()

    assert "size" not in parser.parse("A key requirement is: regular fit.").positive_slots
    assert "size" not in parser.parse("A key requirement is: wide-leg pants.").positive_slots
    assert "size" not in parser.parse("A key requirement is: wide strap.").positive_slots
    assert parser.parse("A key requirement is: width: wide.").positive_slots["size"] == ["wide"]
    assert parser.parse("A key requirement is: narrow width.").positive_slots["size"] == ["narrow"]


def test_parser_keeps_sleeve_length_and_warmth_as_lexical_features() -> None:
    parser = LocalParser()

    sleeve = parser.parse("A key requirement is: short sleeve.")
    warm = parser.parse("This jacket keeps you warm.")

    assert "style" not in sleeve.positive_slots
    assert sleeve.positive_slots["feature"] == ["short sleeve"]
    assert warm.positive_slots["feature"] == ["warm"]
    assert "insulated" not in warm.positive_slots["feature"]


def test_parser_uses_only_controlled_brand_matching() -> None:
    parser = LocalParser()

    assert "brand" not in parser.parse("made from cotton").positive_slots
    assert "brand" not in parser.parse("from recycled materials").positive_slots
    assert "brand" not in parser.parse("from Italy").positive_slots
    assert "brand" not in parser.parse("designed by John").positive_slots
    assert parser.parse("by Nike").positive_slots["brand"] == ["nike"]
    assert parser.parse("made from cotton").positive_slots["material"] == ["cotton"]


def test_parser_prioritises_explicit_category_template_over_fallback_terms() -> None:
    parser = LocalParser()

    parsed = parser.parse("I'm looking for shirts, but I'm still exploring.")
    assert parsed.positive_slots["category"] == ["shirts"]
    parsed = parser.parse("I'm looking for accessories belts, but I'm still exploring.")
    assert parsed.positive_slots["category"] == ["accessories belts"]

    for message in ("bottle cap", "phone ring", "camera bag", "jewelry accessories"):
        assert "category" not in parser.parse(message).positive_slots


def test_boundary_is_detected_before_generic_negative_parsing() -> None:
    parser = LocalParser()

    parsed = parser.parse("I don't have a preference for material; please use your judgment.")
    boundary = parser.detect_boundary("I don't have a preference for material; please use your judgment.")

    assert boundary is not None
    assert boundary.attribute == "material"
    assert not boundary.is_additional
    assert parsed.positive_slots == {}
    assert parsed.negative_slots == {}


def test_other_reply_keeps_each_semicolon_delimited_unknown_constraint() -> None:
    parser = LocalParser()

    parsed = parser.parse(
        "For that, what matters is: package dimensions 9 x 4 inches; machine wash cold."
    )

    assert parsed.positive_slots["feature"] == [
        "package dimensions 9 x 4 inches",
        "machine wash cold",
    ]


def test_sessions_are_isolated_and_slots_accumulate_in_one_intent() -> None:
    manager, _ = _manager_with_state("one")
    manager.reset("two", _profile())

    first = manager.update("one", "I need a cotton shirt.", 1)
    first = manager.update("one", "Blue would be great for hiking.", 2)
    second = manager.update("two", "I need leather boots.", 1)

    assert first.positive_slots["material"] == ["cotton"]
    assert first.positive_slots["color"] == ["blue"]
    assert first.positive_slots["use_case"] == ["hiking"]
    assert "cotton" in first.last_query and "blue" in first.last_query
    assert second.positive_slots["material"] == ["leather"]
    assert "color" not in second.positive_slots


def test_create_is_a_reset_alias_for_agent_integration() -> None:
    manager = StateManager()

    state = manager.create("created", _profile())

    assert state.session_id == "created"
    assert manager.get_state("created") is state


def test_negative_conditions_stay_out_of_the_cumulative_query() -> None:
    manager, _ = _manager_with_state()

    state = manager.update("session-a", "I want a shirt without leather and not slim fit.", 1)

    assert state.negative_slots["material"] == ["leather"]
    assert state.negative_slots["style"] == ["slim fit"]
    assert "leather" not in state.last_query
    assert "slim fit" not in state.last_query


def test_negative_category_is_not_misclassified_as_a_positive_query_term() -> None:
    manager, _ = _manager_with_state()

    state = manager.update("session-a", "I want a jacket, not shoes.", 1)

    assert state.positive_slots["category"] == ["jacket"]
    assert state.negative_slots["category"] == ["shoes"]
    assert "shoes" not in state.last_query


def test_actually_alone_merges_a_new_constraint_without_resetting_state() -> None:
    manager, _ = _manager_with_state()
    manager.update("session-a", "I need a cotton shirt.", 1)

    state = manager.update("session-a", "Actually, I also want blue.", 2)

    assert state.intent_epoch == 0
    assert state.positive_slots["material"] == ["cotton"]
    assert state.positive_slots["color"] == ["blue"]


def test_explicit_override_resets_old_slots_question_records_and_exhaustion() -> None:
    manager, _ = _manager_with_state()
    state = manager.update("session-a", "I need a black cotton shirt.", 1)
    state.asked_specific_attributes.add("material")
    state.no_preference_attributes.add("style")
    state.other_exhausted = True

    state = manager.update(
        "session-a",
        "Actually, ignore my earlier preference. What I need is: leather boots.",
        2,
    )

    assert state.intent_epoch == 1
    assert state.positive_slots["material"] == ["leather"]
    assert state.positive_slots["category"] == ["boots"]
    assert "shirt" not in state.positive_slots["category"]
    assert "black" not in state.positive_slots.get("color", [])
    assert state.asked_specific_attributes == set()
    assert state.no_preference_attributes == set()
    assert not state.other_exhausted


def test_preference_override_preserves_existing_category_when_no_new_category_is_named() -> None:
    manager, _ = _manager_with_state()
    manager.update("session-a", "I'm looking for loafers, but I'm still exploring.", 1)

    state = manager.update(
        "session-a",
        "Actually, ignore my earlier preference. What I need is: leather.",
        2,
    )

    assert state.intent_epoch == 1
    assert state.positive_slots["category"] == ["loafers"]
    assert state.positive_slots["material"] == ["leather"]
    assert state.last_query == "loafers leather"


def test_replacement_signals_reset_only_when_the_turn_has_new_content() -> None:
    manager, state = _manager_with_state()
    manager.update("session-a", "I need a cotton shirt.", 1)

    parsed = manager.parser.parse("Instead, I need a red jacket.")
    assert is_strong_override("Instead, I need a red jacket.", parsed, state)
    state = manager.update("session-a", "Instead, I need a red jacket.", 2)
    assert state.intent_epoch == 1
    assert state.positive_slots["color"] == ["red"]
    assert "cotton" not in state.last_query

    parsed = manager.parser.parse("Rather than leather, I need a wool coat.")
    assert is_strong_override("Rather than leather, I need a wool coat.", parsed, state)
    state = manager.update("session-a", "Rather than leather, I need a wool coat.", 3)
    assert state.intent_epoch == 2
    assert state.positive_slots["material"] == ["wool"]
    assert "leather" not in state.last_query

    parsed = manager.parser.parse("I would rather browse.")
    assert not is_strong_override("I would rather browse.", parsed, state)
    parsed = manager.parser.parse("I might change later.")
    assert not is_strong_override("I might change later.", parsed, state)


def test_replacement_discards_old_contextual_size_and_lexical_feature() -> None:
    manager, _ = _manager_with_state()
    manager.update("session-a", "I need a cotton shirt.", 1)

    state = manager.update(
        "session-a",
        "Rather than size M and long sleeve, I need size L and a waterproof jacket.",
        2,
    )

    assert state.intent_epoch == 1
    assert state.positive_slots["size"] == ["large"]
    assert state.positive_slots["feature"] == ["waterproof"]
    assert "medium" not in state.last_query
    assert "long sleeve" not in state.last_query


def test_replacement_discards_old_budget_before_merging_new_budget() -> None:
    parsed = LocalParser().parse("Instead of over $50, I need under $100.")

    assert parsed.positive_slots["budget"] == ["max:100"]


def test_replacement_discards_old_raw_feature_envelope() -> None:
    parsed = LocalParser().parse(
        "Rather than a key requirement is: short sleeve, I need a waterproof jacket."
    )

    assert parsed.positive_slots["feature"] == ["waterproof"]


def test_other_policy_matches_released_boundary_templates_until_exhausted() -> None:
    manager, _ = _manager_with_state()
    policy = QuestionPolicy()
    state = manager.update("session-a", "I'm looking for shirts, but I'm still exploring.", 1)

    assert policy.choose(state, turn=1) == "other"
    state = manager.update(
        "session-a", "I don't have a preference for other; please use your judgment.", 2
    )
    assert "other" in state.no_preference_attributes
    assert not state.other_exhausted
    assert policy.choose(state, turn=2) == "other"

    state = manager.update(
        "session-a", "I don't have an additional preference for other.", 3
    )
    assert state.other_exhausted
    assert policy.choose(state, turn=3) == "material"


def test_specific_boundary_prevents_reasking_that_attribute() -> None:
    manager, _ = _manager_with_state()
    policy = QuestionPolicy()
    state = manager.update("session-a", "I don't have a preference for material.", 1)
    state.other_exhausted = True

    assert policy.choose(state, turn=1) == "color"


def test_turns_one_to_nine_keep_a_legal_fallback_after_all_specific_fields() -> None:
    manager, state = _manager_with_state()
    policy = QuestionPolicy()
    state.other_exhausted = True
    state.asked_specific_attributes.update(
        {"material", "color", "size", "style", "feature", "use_case", "budget"}
    )

    assert policy.choose(state, turn=9) == "other"


def test_turn_ten_returns_none_and_category_brand_are_never_questions() -> None:
    manager, state = _manager_with_state()
    policy = QuestionPolicy(
        QuestionPolicyConfig(
            mode="information_gain",
            final_turn=10,
            askable_attributes=("category", "brand", "material", "other"),
        )
    )

    assert policy.choose(state, turn=10) is None
    assert policy.choose(state, turn=1) == "material"
    assert "category" not in state.asked_specific_attributes
    assert "brand" not in state.asked_specific_attributes


def test_information_gain_uses_candidate_attribute_coverage_deterministically() -> None:
    manager, state = _manager_with_state()
    policy = QuestionPolicy(
        QuestionPolicyConfig(
            mode="information_gain",
            final_turn=10,
            askable_attributes=("material", "color", "size", "style", "feature", "use_case", "budget"),
        )
    )
    candidates = [
        {"attributes": {"color": ["black"], "material": ["cotton"]}},
        {"attributes": {"color": ["blue"], "material": ["cotton"]}},
        {"attributes": {"color": ["red"], "material": ["cotton"]}},
    ]

    assert policy.choose_attribute(state, candidates, turn=1) == "color"


def test_information_gain_can_read_attribute_coverage_from_candidate_search_text() -> None:
    manager, state = _manager_with_state()
    policy = QuestionPolicy(
        QuestionPolicyConfig(
            mode="information_gain",
            final_turn=10,
            askable_attributes=("material", "color", "size", "style", "feature", "use_case", "budget"),
        )
    )
    candidates = [
        {"search_text": "black cotton shirt"},
        {"search_text": "blue cotton shirt"},
        {"search_text": "red cotton shirt"},
    ]

    assert policy.choose(state, candidates, turn=1) == "color"


def test_information_gain_reads_slots_candidates_and_hyphenated_catalog_text() -> None:
    manager, state = _manager_with_state()
    policy = QuestionPolicy(
        QuestionPolicyConfig(
            mode="information_gain",
            final_turn=10,
            askable_attributes=("feature", "use_case", "other"),
        )
    )
    candidates = [
        Candidate("A1", 1.0, "black water-resistant rain jacket", {"title": "Rain jacket"}),
        Candidate("A2", 0.9, "blue water-resistant shell", {"title": "Rain shell"}),
    ]

    assert policy.choose(state, candidates, turn=1) == "feature"


def test_information_gain_reads_real_slots_candidate_fields() -> None:
    """Shared Candidate uses slots=True and therefore has no __dict__."""
    manager, state = _manager_with_state()
    policy = QuestionPolicy(
        QuestionPolicyConfig(
            mode="information_gain",
            final_turn=10,
            askable_attributes=("feature", "use_case"),
        )
    )
    candidates = [
        Candidate("A1", 1.0, "running shoes", {"title": "Running shoes"}),
        Candidate("A2", 0.9, "hiking boots", {"title": "Hiking boots"}),
    ]

    # use_case has observed coverage/diversity; feature has none. A fixed-order
    # fallback to feature would prove that Candidate fields were not read.
    assert policy.choose(state, candidates, turn=1) == "use_case"


def test_policy_outputs_are_always_official_values_or_none() -> None:
    manager, state = _manager_with_state()
    policy = QuestionPolicy()

    for turn in range(1, 11):
        attribute = policy.choose(state, turn=turn)
        assert attribute is None or attribute in OFFICIAL_ATTRIBUTES
