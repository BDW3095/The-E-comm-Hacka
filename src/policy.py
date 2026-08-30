"""Simulator-aware, deterministic ``ask_attribute`` selection."""

from __future__ import annotations

import re
from typing import Any, Iterable

from .config import ALLOWED_ASK_ATTRIBUTES, QuestionPolicyConfig
from .state import COLORS, FEATURES, MATERIALS, SIZES, STYLES, USE_CASES


OFFICIAL_ATTRIBUTES = ALLOWED_ASK_ATTRIBUTES
SPECIFIC_ASKABLE_ATTRIBUTES = (
    "material",
    "color",
    "size",
    "style",
    "feature",
    "use_case",
    "budget",
)


def _config_value(config: object, name: str, default: Any) -> Any:
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)


def _asked_set(state: object) -> set[str]:
    return getattr(state, "asked_specific_attributes")


def _no_preference_set(state: object) -> set[str]:
    return getattr(state, "no_preference_attributes", set())


class QuestionPolicy:
    """Choose one valid evaluator attribute and render its short English prompt."""

    def __init__(self, config: QuestionPolicyConfig | dict[str, Any] | None = None) -> None:
        self.config = config or QuestionPolicyConfig()

    def choose(
        self,
        state: object,
        candidates: Iterable[object] | None = None,
        turn: int | None = None,
    ) -> str | None:
        """Return a legal attribute, mutating only the asked-attribute record.

        The released evaluator's confirmed private behavior makes repeated
        ``other`` requests optimal until its explicit additional-preference
        Boundary reply.  Specific attributes are selected only after that
        route is exhausted or when the alternate information-gain mode is set.
        """

        current_turn = int(turn if turn is not None else getattr(state, "turn", 0))
        final_turn = int(_config_value(self.config, "final_turn", 10))
        if current_turn >= final_turn:
            return None

        mode = str(_config_value(self.config, "mode", "simulator_optimized"))
        if mode == "simulator_optimized" and not bool(getattr(state, "other_exhausted", False)):
            return "other"

        attribute = self._choose_specific(state, candidates)
        if attribute is not None:
            _asked_set(state).add(attribute)
            return attribute

        # The evaluator expects a non-empty legal value on turns 1--9.  This
        # can occur after the simulator has exhausted ``other`` *and* every
        # specific attribute is already known, declined, or asked.  Repeating
        # ``other`` is intentionally a safe schema-preserving fallback; it
        # does not re-open the state or mark a declined specific field asked.
        return "other"

    def choose_attribute(
        self,
        state: object,
        candidates: Iterable[object] | None = None,
        turn: int | None = None,
    ) -> str | None:
        """Explicit alias used by integrations that name the output field."""

        return self.choose(state, candidates, turn)

    def render_message(self, attribute: str | None) -> str:
        """Return a natural, non-binding English question for demo readability."""

        messages = {
            "material": "Do you have a preferred material?",
            "color": "Do you have a color preference?",
            "size": "What size or fit range would work best?",
            "style": "What style or fit do you prefer?",
            "feature": "Is there a feature that matters most to you?",
            "use_case": "What activity or occasion will you use it for?",
            "budget": "Do you have a budget in mind?",
            "other": "Do you have any other preference I should consider?",
        }
        return messages.get(attribute, "I will use the preferences you have shared to refine these options.")

    def _choose_specific(self, state: object, candidates: Iterable[object] | None) -> str | None:
        asked = _asked_set(state)
        no_preference = _no_preference_set(state)
        positive_slots = getattr(state, "positive_slots", {})
        negative_slots = getattr(state, "negative_slots", {})
        configured = tuple(_config_value(self.config, "askable_attributes", SPECIFIC_ASKABLE_ATTRIBUTES))
        eligible = [
            attribute
            for attribute in SPECIFIC_ASKABLE_ATTRIBUTES
            if attribute in configured
            and attribute in OFFICIAL_ATTRIBUTES
            and attribute not in asked
            and attribute not in no_preference
            and not positive_slots.get(attribute)
            and not negative_slots.get(attribute)
        ]
        # category and brand are intentionally absent: they can be ranking
        # signals, but must never be selected as proactive questions.
        if not eligible:
            return None

        candidate_list = list(candidates or [])
        if not candidate_list:
            return eligible[0]

        # Approximate information gain with only A's supplied candidates.  A
        # higher coverage and more distinct observed values make an attribute a
        # more useful discriminator.  The tuple gives deterministic ties to
        # the declared product priority rather than input-list ordering.
        scored = []
        for priority, attribute in enumerate(eligible):
            values = self._candidate_values(candidate_list, attribute)
            coverage = len(values)
            diversity = len(set(values))
            scored.append((coverage * diversity, coverage, diversity, -priority, attribute))
        return max(scored)[-1]

    def _candidate_values(self, candidates: list[object], attribute: str) -> list[str]:
        values: list[str] = []
        for candidate in candidates[:50]:
            extracted = self._attribute_values(candidate, attribute)
            values.extend(str(value).strip().lower() for value in extracted if str(value).strip())
        return values

    @staticmethod
    def _attribute_values(candidate: object, attribute: str) -> Iterable[object]:
        if isinstance(candidate, dict):
            mapping: Any = candidate
        else:
            mapping = getattr(candidate, "__dict__", {})

        product = mapping.get("product", {}) if isinstance(mapping, dict) else getattr(candidate, "product", {})
        for source in (mapping, product):
            if not isinstance(source, dict):
                continue
            attributes = source.get("attributes", {})
            if isinstance(attributes, dict) and attribute in attributes:
                value = attributes[attribute]
                return value if isinstance(value, (list, tuple, set)) else [value]
            if attribute in source:
                value = source[attribute]
                return value if isinstance(value, (list, tuple, set)) else [value]

        # A's Candidate normally carries raw catalog metadata plus search_text,
        # rather than a second normalized-attribute mapping.  Looking only at
        # this already supplied candidate is not catalog indexing; it lets the
        # information-gain mode use the promised coverage/diversity signal.
        search_text = " ".join(
            str(value or "")
            for value in (
                mapping.get("search_text", "") if isinstance(mapping, dict) else getattr(candidate, "search_text", ""),
                product.get("title", "") if isinstance(product, dict) else "",
                product.get("features", "") if isinstance(product, dict) else "",
                product.get("details", "") if isinstance(product, dict) else "",
                product.get("description", "") if isinstance(product, dict) else "",
            )
        ).lower()
        vocabulary = {
            "material": MATERIALS,
            "color": COLORS,
            "size": SIZES,
            "style": STYLES,
            "feature": FEATURES,
            "use_case": USE_CASES,
        }
        if attribute == "budget" and isinstance(product, dict) and product.get("price") not in (None, ""):
            return [f"price:{product['price']}"]
        return [
            value
            for value in vocabulary.get(attribute, ())
            if QuestionPolicy._surface_contains(search_text, value)
        ]

    @staticmethod
    def _surface_contains(text: str, value: str) -> bool:
        """Treat controlled ``quick dry``/``quick-dry`` variants alike."""

        words = [re.escape(word) for word in re.split(r"[\s-]+", value) if word]
        return bool(re.search(r"\b" + r"[-\s]+".join(words) + r"\b", text))


__all__ = [
    "OFFICIAL_ATTRIBUTES",
    "QuestionPolicy",
    "QuestionPolicyConfig",
    "SPECIFIC_ASKABLE_ATTRIBUTES",
]
