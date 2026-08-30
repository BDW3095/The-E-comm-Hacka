"""Deterministic conversation-state management for the shopping agent.

This module deliberately has no catalog, evaluator, model, or network
dependency.  It turns an individual user turn into structured constraints,
keeps each session's current intent isolated, and produces a positive-only
query for the retrieval layer.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import Any, Iterable

from .config import SLOT_KEYS
from .types import ParsedTurn, SessionState

MATERIALS = (
    "cotton",
    "polyester",
    "nylon",
    "leather",
    "wool",
    "spandex",
    "silk",
    "rayon",
    "denim",
    "linen",
    "suede",
    "cashmere",
    "fleece",
    "canvas",
    "mesh",
)
COLORS = (
    "black",
    "white",
    "blue",
    "red",
    "pink",
    "green",
    "brown",
    "gray",
    "purple",
    "yellow",
    "orange",
    "beige",
    "navy",
    "gold",
    "silver",
    "tan",
)
COLOR_ALIASES = {"grey": "gray"}
SIZES = (
    "xs",
    "small",
    "medium",
    "large",
    "xl",
    "xxl",
    "xxxl",
    "petite",
    "plus size",
    "tall",
)
STYLES = (
    "casual",
    "formal",
    "athletic",
    "vintage",
    "classic",
    "bohemian",
    "sporty",
    "slim fit",
    "relaxed fit",
    "crew neck",
    "v-neck",
)
USE_CASES = (
    "hiking",
    "running",
    "gym",
    "winter",
    "summer",
    "outdoor",
    "work",
    "travel",
    "yoga",
    "swimming",
    "wedding",
    "party",
    "everyday",
)
FEATURES = (
    "waterproof",
    "water resistant",
    "windproof",
    "breathable",
    "moisture wicking",
    "quick dry",
    "wrinkle resistant",
    "lightweight",
    "insulated",
    "stretch",
    "adjustable",
    "reversible",
    "reinforced",
    "packable",
    "machine washable",
    "anti slip",
    "non slip",
    "uv protection",
    "odor resistant",
)
PRODUCT_TERMS = (
    "t-shirt",
    "t-shirts",
    "tshirt",
    "shirt",
    "shirts",
    "blouse",
    "blouses",
    "jacket",
    "jackets",
    "hoodie",
    "hoodies",
    "sweater",
    "sweaters",
    "pants",
    "jeans",
    "shorts",
    "skirt",
    "skirts",
    "shoes",
    "shoe",
    "sneakers",
    "boots",
    "boot",
    "sandals",
    "socks",
    "underwear",
    "belt",
    "hat",
    "necklace",
    "bracelet",
)
COMMON_BRANDS = (
    "adidas",
    "asics",
    "calvin klein",
    "carhartt",
    "champion",
    "columbia",
    "crocs",
    "levi's",
    "nike",
    "new balance",
    "puma",
    "reebok",
    "skechers",
    "tommy hilfiger",
    "under armour",
)

_TOKEN_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_NEGATIVE_SCOPE_RE = re.compile(
    r"\b(?:not|no|without|exclude|avoid|do\s+not|don't)\b[^,;.!?]*",
    re.IGNORECASE,
)
_EXPLICIT_OVERRIDE_RE = re.compile(
    r"\b(?:ignore\s+(?:my\s+)?(?:earlier|previous)\s+(?:preference|request|requirements?)"
    r"|forget\s+(?:what\s+)?i\s+(?:said|mentioned)"
    r"|start\s+over)\b",
    re.IGNORECASE,
)
_REPLACEMENT_OVERRIDE_RE = re.compile(
    r"\b(?:instead|rather\s+than|change\s+from|switch\s+from)\b",
    re.IGNORECASE,
)
_BOUNDARY_RE = re.compile(
    r"\bi\s+(?:do\s+not|don't)\s+have\s+"
    r"(?:(?P<additional>an\s+additional)\s+|a\s+)?preference\s+for\s+"
    r"(?P<attribute>[a-z_\- ]+?)(?:\s*(?:;|,|\.|!|\?|$))",
    re.IGNORECASE,
)

_SIZE_CODE_MAP = {"s": "small", "m": "medium", "l": "large"}
_SIZE_CODE_AFTER_LABEL_RE = re.compile(
    r"\b(?:size|sizing)\s*(?:(?:is|equals?)\s*)?[:=#-]?\s*\(?(?P<code>[sml])(?!\s*/)\)?\b",
    re.IGNORECASE,
)
_SIZE_CODE_BEFORE_LABEL_RE = re.compile(
    r"\b(?P<code>[sml])\s*(?:-|\s)+(?:size|sized)\b(?!\s+chart\b)",
    re.IGNORECASE,
)
_SIZE_CONTEXT_VALUE_RE = re.compile(
    r"\b(?:size(?:\s+type)?|size\s+type)\s*(?:(?:is|equals?)\s*)?[:=#-]?\s*(?P<value>regular)\b",
    re.IGNORECASE,
)
_WIDTH_CONTEXT_VALUE_RE = re.compile(
    r"\b(?:shoe\s+|foot\s+)?width\s*(?:(?:is|equals?)\s*)?[:=#-]?\s*(?P<value>wide|narrow)\b"
    r"|\b(?P<reverse>wide|narrow)\s+width\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BoundaryResult:
    """A simulator Boundary reply, detected before negative-slot parsing."""

    attribute: str
    is_additional: bool


def _normalise_space(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _append_unique(values: list[str], additions: Iterable[str]) -> None:
    known = set(values)
    for value in additions:
        if value and value not in known:
            values.append(value)
            known.add(value)


def _canonical_attribute(value: str) -> str | None:
    lowered = _normalise_space(value).replace("-", " ")
    aliases = {
        "colour": "color",
        "fabric": "material",
        "fit": "style",
        "occasion": "use_case",
        "use case": "use_case",
        "usage": "use_case",
        "features": "feature",
        "other preferences": "other",
        "additional preference": "other",
    }
    lowered = aliases.get(lowered, lowered)
    if lowered in SLOT_KEYS or lowered == "other":
        return lowered
    return None


def _term_pattern(value: str) -> re.Pattern[str]:
    """Match a controlled term across ordinary-space and hyphen spellings.

    Catalog metadata uses both ``quick-dry`` and ``quick dry`` (and likewise
    for several size/style values).  The active slot keeps one canonical,
    space-separated spelling, while this matcher accepts either surface form.
    """

    words = [re.escape(word) for word in re.split(r"[\s-]+", value) if word]
    return re.compile(r"\b" + r"[-\s]+".join(words) + r"\b", re.IGNORECASE)


def _match_in_negative_scope(start: int, end: int, scopes: list[tuple[int, int]]) -> bool:
    return any(scope_start <= start and end <= scope_end for scope_start, scope_end in scopes)


class LocalParser:
    """Rule-based parser for the released, deterministic evaluator templates."""

    def detect_boundary(self, message: str) -> BoundaryResult | None:
        """Return a Boundary response before trying to interpret ``no`` as negation."""

        match = _BOUNDARY_RE.search(str(message or ""))
        if not match:
            return None
        attribute = _canonical_attribute(match.group("attribute"))
        if attribute is None:
            return None
        return BoundaryResult(attribute=attribute, is_additional=bool(match.group("additional")))

    def parse(self, message: str) -> ParsedTurn:
        """Parse visible positive and negative constraints without external services."""

        raw_message = str(message or "")
        # A Boundary message is intentionally not a negative preference.  This
        # check must remain before all generic ``no``/``not`` handling.
        if self.detect_boundary(raw_message) is not None:
            return self._parsed({}, {}, None)

        lowered = _normalise_space(raw_message)
        positive: defaultdict[str, list[str]] = defaultdict(list)
        negative: defaultdict[str, list[str]] = defaultdict(list)
        negative_scopes = [(match.start(), match.end()) for match in _NEGATIVE_SCOPE_RE.finditer(lowered)]
        replaced_value_scopes = self._replaced_value_scopes(lowered)

        self._extract_known_values(lowered, positive, negative, negative_scopes, replaced_value_scopes)
        self._extract_contextual_sizes(lowered, positive, negative, negative_scopes)
        self._extract_lexical_only_features(lowered, positive, negative, negative_scopes)
        self._extract_budget(lowered, positive)
        self._extract_brand(lowered, positive, negative, negative_scopes, replaced_value_scopes)
        self._extract_category(
            lowered,
            positive,
            negative,
            negative_scopes,
            replaced_value_scopes,
        )
        self._extract_explicit_feature(lowered, positive, negative, negative_scopes)

        normalised_query = self._query_from_slots(positive)
        return self._parsed(dict(positive), dict(negative), normalised_query)

    @staticmethod
    def _replaced_value_scopes(text: str) -> list[tuple[int, int]]:
        """Locate the *old* side of a replacement statement.

        In "rather than leather, I need cotton", leather describes the
        superseded request and must not be merged back into the new intent.
        """

        scopes: list[tuple[int, int]] = []
        patterns = (
            re.compile(r"\b(?:instead\s+of|rather\s+than)\s+([^,;.]+?)(?=\s*(?:,|;|\.|$))", re.I),
            re.compile(r"\b(?:change|switch)\s+from\s+(.+?)\s+to\s+", re.I),
        )
        for pattern in patterns:
            for match in pattern.finditer(text):
                scopes.append((match.start(1), match.end(1)))
        return scopes

    def _parsed(
        self,
        positive: dict[str, list[str]],
        negative: dict[str, list[str]],
        normalized_query: str | None,
    ) -> ParsedTurn:
        return ParsedTurn(
            positive_slots={key: values for key, values in positive.items() if values},
            negative_slots={key: values for key, values in negative.items() if values},
            normalized_query=normalized_query or None,
            is_override=False,
        )

    def _extract_known_values(
        self,
        text: str,
        positive: defaultdict[str, list[str]],
        negative: defaultdict[str, list[str]],
        negative_scopes: list[tuple[int, int]],
        replaced_value_scopes: list[tuple[int, int]],
    ) -> None:
        groups = {
            "material": MATERIALS,
            "color": (*COLORS, *COLOR_ALIASES),
            "size": SIZES,
            "style": STYLES,
            "use_case": USE_CASES,
            "feature": FEATURES,
        }
        for attribute, values in groups.items():
            for value in values:
                # Prefer a meaningful multi-word fit over its component word:
                # ``slim fit`` is one constraint, not two penalties.
                if value in {"slim", "relaxed"} and _term_pattern(f"{value} fit").search(text):
                    continue
                for match in _term_pattern(value).finditer(text):
                    if _match_in_negative_scope(match.start(), match.end(), replaced_value_scopes):
                        continue
                    canonical = COLOR_ALIASES.get(value, value)
                    destination = negative if _match_in_negative_scope(
                        match.start(), match.end(), negative_scopes
                    ) else positive
                    _append_unique(destination[attribute], [canonical])

    def _extract_contextual_sizes(
        self,
        text: str,
        positive: defaultdict[str, list[str]],
        negative: defaultdict[str, list[str]],
        negative_scopes: list[tuple[int, int]],
    ) -> None:
        """Parse S/M/L and ambiguous size words only with explicit size context."""

        for pattern in (_SIZE_CODE_AFTER_LABEL_RE, _SIZE_CODE_BEFORE_LABEL_RE):
            for match in pattern.finditer(text):
                code = match.group("code").lower()
                value = _SIZE_CODE_MAP[code]
                start, end = match.span("code")
                destination = negative if _match_in_negative_scope(
                    start, end, negative_scopes
                ) else positive
                _append_unique(destination["size"], [value])

        for match in _SIZE_CONTEXT_VALUE_RE.finditer(text):
            value = match.group("value").lower()
            start, end = match.span("value")
            destination = negative if _match_in_negative_scope(
                start, end, negative_scopes
            ) else positive
            _append_unique(destination["size"], [value])

        for match in _WIDTH_CONTEXT_VALUE_RE.finditer(text):
            value = (match.group("value") or match.group("reverse")).lower()
            group_name = "value" if match.group("value") else "reverse"
            start, end = match.span(group_name)
            destination = negative if _match_in_negative_scope(
                start, end, negative_scopes
            ) else positive
            _append_unique(destination["size"], [value])

    def _extract_lexical_only_features(
        self,
        text: str,
        positive: defaultdict[str, list[str]],
        negative: defaultdict[str, list[str]],
        negative_scopes: list[tuple[int, int]],
    ) -> None:
        """Keep sleeve length and warmth lexical without promoting them to style."""

        for value in ("long sleeve", "short sleeve", "sleeveless"):
            for match in _term_pattern(value).finditer(text):
                destination = negative if _match_in_negative_scope(
                    match.start(), match.end(), negative_scopes
                ) else positive
                _append_unique(destination["feature"], [value])

        warm_pattern = re.compile(r"\b(?:keep(?:s)?|keeping|stay(?:s)?)\s+(?:you\s+)?warm\b", re.I)
        for match in warm_pattern.finditer(text):
            destination = negative if _match_in_negative_scope(
                match.start(), match.end(), negative_scopes
            ) else positive
            _append_unique(destination["feature"], ["warm"])

    def _extract_budget(self, text: str, positive: defaultdict[str, list[str]]) -> None:
        number = r"\$?\s*(\d+(?:\.\d{1,2})?)"
        patterns = (
            ("max", re.compile(r"\b(?:under|below|less\s+than|up\s+to|at\s+most|<=)\s*" + number, re.I)),
            ("min", re.compile(r"\b(?:over|above|more\s+than|at\s+least|>=)\s*" + number, re.I)),
            ("target", re.compile(r"\b(?:around|about|approximately)\s*" + number, re.I)),
        )
        for kind, pattern in patterns:
            for match in pattern.finditer(text):
                value = float(match.group(1))
                rendered = f"{value:g}"
                _append_unique(positive["budget"], [f"{kind}:{rendered}"])

    def _extract_brand(
        self,
        text: str,
        positive: defaultdict[str, list[str]],
        negative: defaultdict[str, list[str]],
        negative_scopes: list[tuple[int, int]],
        replaced_value_scopes: list[tuple[int, int]],
    ) -> None:
        for brand in COMMON_BRANDS:
            for match in _term_pattern(brand).finditer(text):
                if _match_in_negative_scope(match.start(), match.end(), replaced_value_scopes):
                    continue
                destination = negative if _match_in_negative_scope(
                    match.start(), match.end(), negative_scopes
                ) else positive
                _append_unique(destination["brand"], [brand])

    def _extract_category(
        self,
        text: str,
        positive: defaultdict[str, list[str]],
        negative: defaultdict[str, list[str]],
        negative_scopes: list[tuple[int, int]],
        replaced_value_scopes: list[tuple[int, int]],
    ) -> None:
        # The evaluator starts with "I'm looking for <coarse category>".  Keep
        # that explicit category wording as the primary category signal.
        match = re.search(
            r"\b(?:i'?m\s+)?looking\s+for\s+(?:a|an|some)?\s*(.+?)"
            r"(?=\s*(?:,|\.|;|but\b|a\s+key\s+requirement\b|$))",
            text,
            re.IGNORECASE,
        )
        if match:
            phrase = _normalise_space(match.group(1))
            phrase = re.sub(r"\b(?:still|exploring|item|something)\b", " ", phrase)
            phrase = re.sub(r"[^a-z0-9 ]+", " ", phrase)
            phrase = _normalise_space(phrase)
            if phrase and len(phrase.split()) <= 8:
                _append_unique(positive["category"], [phrase])
                return

        # Outside the released category template, a small product taxonomy is
        # only a fallback.  It must not add a second category to a template
        # message that already established one explicitly.
        for term in PRODUCT_TERMS:
            for match in _term_pattern(term).finditer(text):
                if _match_in_negative_scope(match.start(), match.end(), replaced_value_scopes):
                    continue
                destination = negative if _match_in_negative_scope(
                    match.start(), match.end(), negative_scopes
                ) else positive
                _append_unique(destination["category"], [term])

    def _extract_explicit_feature(
        self,
        text: str,
        positive: defaultdict[str, list[str]],
        negative: defaultdict[str, list[str]],
        negative_scopes: list[tuple[int, int]],
    ) -> None:
        pattern = re.compile(
            r"\b(?:a\s+key\s+requirement|what\s+i\s+need|what\s+matters)\s+is\s*:\s*([^.]*)",
            re.IGNORECASE,
        )
        for match in pattern.finditer(text):
            # ``customer_reply(..., "other", ...)`` joins up to two hidden
            # constraints with a semicolon.  Preserve both unknown metadata
            # phrases, not only the first one, while known materials/colors
            # continue to be extracted by the normal slot dictionaries.
            for raw_value in match.group(1).split(";"):
                value = _normalise_space(raw_value).strip(" -,:;")
                if not value:
                    continue
                value_start = match.start(1) + match.group(1).find(raw_value)
                destination = negative if _match_in_negative_scope(
                    value_start, value_start + len(raw_value), negative_scopes
                ) else positive
                _append_unique(destination["feature"], [value[:160]])

    def _query_from_slots(self, positive: dict[str, list[str]]) -> str:
        terms: list[str] = []
        for attribute in SLOT_KEYS:
            if attribute == "budget":
                continue
            for value in positive.get(attribute, []):
                _append_unique(terms, [value])
        return " ".join(terms)


def is_strong_override(message: str, parsed: ParsedTurn, state: SessionState) -> bool:
    """Recognise replacement, not ordinary accumulation, of a user intent.

    ``actually`` is deliberately absent from both signal groups.  The released
    override template also says "ignore my earlier preference", so it is still
    recognised through the explicit-reset branch.
    """

    text = str(message or "")
    if _EXPLICIT_OVERRIDE_RE.search(text):
        return True
    if not _REPLACEMENT_OVERRIDE_RE.search(text):
        return False
    return bool(
        getattr(parsed, "normalized_query", None)
        or getattr(parsed, "positive_slots", None)
        or getattr(parsed, "negative_slots", None)
    )


class StateManager:
    """Own the mutable state of isolated shopping sessions."""

    def __init__(self, parser: LocalParser | None = None) -> None:
        self.parser = parser or LocalParser()
        self._states: dict[str, SessionState] = {}

    def reset(self, session_id: str, user_profile: dict[str, Any] | None) -> None:
        """Create or replace the short-term state for one evaluator session."""

        profile = user_profile or {}
        raw_tags = profile.get("preference_tags", []) if isinstance(profile, dict) else []
        profile_tags = [_normalise_space(tag) for tag in raw_tags if _normalise_space(tag)]
        self._states[session_id] = self._new_state(session_id, profile_tags)

    def create(self, session_id: str, user_profile: dict[str, Any] | None) -> SessionState:
        """Create a state and return it (an integration-friendly reset alias)."""

        self.reset(session_id, user_profile)
        return self.get_state(session_id)

    def get_state(self, session_id: str) -> SessionState:
        try:
            return self._states[session_id]
        except KeyError as error:
            raise RuntimeError("reset must be called before state update") from error

    def update(self, session_id: str, message: str, turn: int) -> SessionState:
        """Parse a turn, apply Boundary/Override semantics, and update query."""

        parsed = self.parser.parse(message)
        return self.update_or_reset(session_id, parsed, message, turn)

    def update_or_reset(
        self,
        session_id: str,
        parsed: ParsedTurn,
        message: str,
        turn: int,
    ) -> SessionState:
        """Apply an already parsed turn; useful to an integrating Agent wrapper."""

        state = self.get_state(session_id)
        boundary = self.parser.detect_boundary(message)
        should_reset = boundary is None and is_strong_override(message, parsed, state)
        if should_reset:
            self._reset_current_intent(state)
            try:
                parsed.is_override = True
            except (AttributeError, TypeError):
                pass

        if boundary is not None:
            self._apply_boundary(state, boundary)
        else:
            self._merge_slots(state, getattr(parsed, "positive_slots", {}), getattr(parsed, "negative_slots", {}))

        state.messages.append(str(message or ""))
        state.turn = int(turn)
        state.last_query = self.build_query(state)
        state.mode = self._infer_mode(state)
        return state

    def build_query(self, state: SessionState) -> str:
        """Build a deterministic, cumulative, positive-only retrieval query."""

        terms: list[str] = []
        for attribute in SLOT_KEYS:
            if attribute == "budget":
                continue
            values = getattr(state, "positive_slots", {}).get(attribute, [])
            _append_unique(terms, (_normalise_space(value) for value in values))
        return " ".join(term for term in terms if term)

    def _new_state(self, session_id: str, profile_tags: list[str]) -> SessionState:
        fields = {
            "session_id": session_id,
            "profile_tags": profile_tags,
            "messages": [],
            "positive_slots": {},
            "negative_slots": {},
            "asked_specific_attributes": set(),
            "no_preference_attributes": set(),
            "other_exhausted": False,
            "intent_epoch": 0,
            "turn": 0,
            "last_query": "",
            "mode": "browsing",
        }
        return SessionState(**fields)

    def _reset_current_intent(self, state: SessionState) -> None:
        state.positive_slots.clear()
        state.negative_slots.clear()
        self._asked_set(state).clear()
        self._no_preference_set(state).clear()
        state.other_exhausted = False
        state.intent_epoch = int(getattr(state, "intent_epoch", 0)) + 1

    def _apply_boundary(self, state: SessionState, boundary: BoundaryResult) -> None:
        # A first "no preference for other" is deliberately *not* exhaustion:
        # the released simulator can disclose additional constraints after the
        # next repeated other request.  Only its explicit "additional" reply
        # closes that route.
        if boundary.attribute == "other" and boundary.is_additional:
            state.other_exhausted = True
            return
        self._no_preference_set(state).add(boundary.attribute)

    def _merge_slots(
        self,
        state: SessionState,
        positive_slots: dict[str, list[str]],
        negative_slots: dict[str, list[str]],
    ) -> None:
        positive = state.positive_slots
        negative = state.negative_slots
        for attribute, values in positive_slots.items():
            if attribute not in SLOT_KEYS:
                continue
            canonical_values = [_normalise_space(value) for value in values if _normalise_space(value)]
            if attribute == "budget":
                self._merge_budget(positive, canonical_values)
            else:
                _append_unique(positive.setdefault(attribute, []), canonical_values)
            existing_negative = negative.get(attribute, [])
            negative[attribute] = [value for value in existing_negative if value not in canonical_values]
            if not negative[attribute]:
                negative.pop(attribute, None)

        for attribute, values in negative_slots.items():
            if attribute not in SLOT_KEYS:
                continue
            canonical_values = [_normalise_space(value) for value in values if _normalise_space(value)]
            _append_unique(negative.setdefault(attribute, []), canonical_values)
            existing_positive = positive.get(attribute, [])
            positive[attribute] = [value for value in existing_positive if value not in canonical_values]
            if not positive[attribute]:
                positive.pop(attribute, None)

    @staticmethod
    def _merge_budget(slots: dict[str, list[str]], values: list[str]) -> None:
        existing = list(slots.get("budget", []))
        for value in values:
            kind, _, _amount = value.partition(":")
            if kind in {"min", "max", "target"}:
                existing = [item for item in existing if not item.startswith(f"{kind}:")]
            if value not in existing:
                existing.append(value)
        if existing:
            slots["budget"] = existing

    @staticmethod
    def _asked_set(state: SessionState) -> set[str]:
        return state.asked_specific_attributes

    @staticmethod
    def _no_preference_set(state: SessionState) -> set[str]:
        return state.no_preference_attributes

    @staticmethod
    def _infer_mode(state: SessionState) -> str:
        hard_attributes = ("material", "color", "size", "style", "brand", "budget")
        hard_count = sum(bool(state.positive_slots.get(attribute)) for attribute in hard_attributes)
        return "buying" if hard_count else "browsing"


def build_query(state: SessionState) -> str:
    """Convenience function for callers that hold a state but not its manager."""

    return StateManager().build_query(state)


__all__ = [
    "BoundaryResult",
    "COLORS",
    "FEATURES",
    "LocalParser",
    "MATERIALS",
    "ParsedTurn",
    "SLOT_KEYS",
    "SessionState",
    "StateManager",
    "USE_CASES",
    "build_query",
    "is_strong_override",
]
