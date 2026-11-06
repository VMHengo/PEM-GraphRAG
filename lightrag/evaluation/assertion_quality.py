"""Conservative, offline quality hints for extracted directed assertions.

These rules identify review priorities, not truth or a reason to delete an edge.
"""

from __future__ import annotations

import re
from typing import Any


QUALITY_RULE_VERSION = "0.1.0"
_SIGNED_RELATIONS = {"increases", "decreases", "reduces", "degrades", "improves"}
_SIGNED_CUES = re.compile(
    r"\b(increas\w*|decreas\w*|reduc\w*|rais\w*|lower\w*|higher|lower|"
    r"thicken\w*|degrad\w*|improv\w*)\b", re.I
)
_SOH = re.compile(r"\b\d{2,3}\s*%\s*SOH\b", re.I)
_QUANTITY = re.compile(r"\b(proportion|ratio|fraction|percentage)\s+of\b", re.I)
_CAUSAL_ACTOR = re.compile(
    r"^(?P<actor>[A-Za-z][A-Za-z\s-]{2,65}?)\s+"
    r"(?:causes?|results?\s+in|leads?\s+to|increases?|decreases?)\b", re.I
)
_MODIFIERS = {"severe", "increased", "decreased", "higher", "lower", "difficult"}
_STOP = {"the", "in", "of", "to", "and", "during", "a", "an", "is"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.casefold())


def _mentions(text: str, name: str) -> bool:
    tokens = _words(name)
    if not tokens:
        return False
    normalized = " " + " ".join(_words(text)) + " "
    return f" {' '.join(tokens)} " in normalized


def _flag(code: str, reason: str, *, priority: str = "review") -> dict[str, str]:
    return {"code": code, "priority": priority, "reason": reason}


def quality_hints(hop: dict[str, Any], source: dict[str, Any]) -> list[dict[str, str]]:
    """Return explainable warnings based on a supplied source proposal.

    The source proposal may be incomplete or incorrectly localized. A missing
    cue never proves that the relation is false.
    """

    relation = str(hop.get("relation") or "").casefold()
    source_name = str(hop.get("source") or "")
    target_name = str(hop.get("target") or "")
    description = str(hop.get("description") or "")
    excerpt = source.get("context_excerpt") or {}
    span_text = str(excerpt.get("text") or "") if isinstance(excerpt, dict) else ""
    span_status = str(excerpt.get("status") or "") if isinstance(excerpt, dict) else ""
    flags: list[dict[str, str]] = []

    if span_status != "exact_text_match":
        flags.append(_flag(
            "source_not_exact_quote",
            "The displayed span is a retrieval lead, not a verbatim assertion quote.",
            priority="evidence",
        ))

    if relation in _SIGNED_RELATIONS and not _SIGNED_CUES.search(description):
        flags.append(_flag(
            "signed_effect_not_in_description",
            "The relation encodes a signed effect but its description does not state one.",
        ))

    actor = _CAUSAL_ACTOR.match(description)
    if actor:
        actor_terms = set(_words(actor.group("actor"))) - _MODIFIERS - _STOP
        source_terms = set(_words(source_name)) - _MODIFIERS - _STOP
        if actor_terms and source_terms and not actor_terms.intersection(source_terms):
            flags.append(_flag(
                "alternative_causal_actor",
                "The description attributes the effect to an actor other than the graph source.",
            ))

    if relation in _SIGNED_RELATIONS and re.search(r"\bindicat\w*\b", description, re.I):
        flags.append(_flag(
            "association_as_cause",
            "The description says the source indicates the effect, not necessarily causes it.",
        ))

    if relation in _SIGNED_RELATIONS and span_text and target_name:
        # A claim about a fraction is not automatically a claim about the amount
        # or condition of the material named as the target node.
        target_terms = [term for term in _words(target_name) if term not in _STOP]
        target_core = " ".join(target_terms[:2])
        if _QUANTITY.search(span_text) and not any(
            word in target_name.casefold() for word in ("proportion", "ratio", "fraction", "percentage")
        ) and len(target_terms) >= 2 and target_core in " ".join(_words(span_text)):
            flags.append(_flag(
                "quantity_target_mismatch",
                "The span discusses a proportion, while the target names the material itself.",
            ))

    soh_values = {match.group().replace(" ", "").casefold() for match in _SOH.finditer(span_text)}
    if soh_values and not all(value in (description + source_name + target_name).replace(" ", "").casefold() for value in soh_values):
        flags.append(_flag(
            "soh_value_not_in_claim",
            "The source span includes an SOH value absent from the structured claim.",
            priority="context",
        ))

    return flags
