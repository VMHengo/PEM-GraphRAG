"""Quality hints prioritize review; they never assert that an edge is false."""

from lightrag.evaluation.assertion_quality import quality_hints


def _codes(source: str, relation: str, target: str, description: str, span: str):
    hop = {
        "source": source, "relation": relation, "target": target,
        "description": description,
    }
    proposal = {"context_excerpt": {"text": span, "status": "candidate_related_text"}}
    return {flag["code"] for flag in quality_hints(hop, proposal)}


def test_unsigned_description_is_reviewed():
    codes = _codes(
        "Current Rate Increase", "increases", "Heat Generation",
        "A larger current rate has a more serious effect on heat generation.",
        "A larger current rate has a more serious effect on heat generation.",
    )
    assert "signed_effect_not_in_description" in codes


def test_alternative_actor_is_reviewed():
    codes = _codes(
        "Severe Internal Polarization", "increases", "AC Impedance",
        "Severe degradation causes a significant increase in AC impedance.",
        "Severe degradation causes a significant increase in AC impedance.",
    )
    assert "alternative_causal_actor" in codes


def test_proportion_is_not_material_amount():
    codes = _codes(
        "Aging", "degrades", "Inorganic Components In SEI Film",
        "Aging decreases the proportion of inorganic components in the film.",
        "Aging decreases the proportion of inorganic components in the film.",
    )
    assert "quantity_target_mismatch" in codes


def test_indication_is_not_automatically_causation():
    codes = _codes(
        "Temperature Rise Rate", "increases", "Cell Temperature",
        "An increased rise rate indicates a higher cell temperature.",
        "An increased rise rate indicates a higher cell temperature.",
    )
    assert "association_as_cause" in codes


def test_direct_signed_claim_is_not_flagged():
    codes = _codes(
        "Diffusion Difficulty", "increases", "Warburg Resistance",
        "Diffusion difficulty increases Warburg resistance.",
        "Diffusion difficulty increases Warburg resistance.",
    )
    assert "signed_effect_not_in_description" not in codes
    assert "alternative_causal_actor" not in codes
