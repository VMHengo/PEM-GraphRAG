"""Conservative, opt-in PEM ontology annotations for graph properties."""

from __future__ import annotations

import json
import os
import hashlib
import re
import unicodedata
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path


_MAPPING_STATUSES = {"mapped", "conditional", "ambiguous", "unmapped"}


def ontology_annotations_enabled() -> bool:
    return os.environ.get("ONTOLOGY_ANNOTATION_ENABLED", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def ontology_annotation_revision() -> dict[str, str | bool]:
    if not ontology_annotations_enabled():
        return {"enabled": False}
    path = os.environ.get(
        "PEM_ONTOLOGY_MAPPING_PATH",
        str(
            Path(__file__).resolve().parent.parent / "ontology" / "pem_mapping_v1.json"
        ),
    )
    content = Path(path).read_bytes()
    mapping = _load_mapping(path, Path(path).stat().st_mtime_ns)
    return {
        "enabled": True,
        "mapping_version": str(mapping["mapping_version"]),
        "mapping_sha256": hashlib.sha256(content).hexdigest(),
    }


@lru_cache(maxsize=4)
def _load_mapping(path: str, mtime_ns: int) -> dict:
    with Path(path).open(encoding="utf-8") as stream:
        mapping = json.load(stream)
    if mapping.get("schema_version") != 1 or not mapping.get("mapping_version"):
        raise ValueError("Unsupported PEM ontology mapping schema")
    for section in ("entity_types", "relations"):
        if not isinstance(mapping.get(section), list):
            raise ValueError(f"Missing PEM ontology mapping section: {section}")
        for entry in mapping[section]:
            if (
                not isinstance(entry, Mapping)
                or not str(entry.get("label") or "").strip()
            ):
                raise ValueError(f"Invalid PEM ontology mapping entry in {section}")
            if entry.get("status") not in _MAPPING_STATUSES:
                raise ValueError(f"Invalid PEM ontology mapping status in {section}")
            if entry["status"] == "mapped" and not entry.get("iri"):
                raise ValueError(f"Mapped ontology label has no IRI: {entry['label']}")
    return mapping


def _normalize_label(value: object) -> str:
    """Match the reviewed resolver's conservative surface normalization."""

    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", text)
    text = text.casefold().translate(str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue"}))
    return re.sub(r"[^\w]+", "_", text).strip("_")


def _matching_entries(mapping: dict, section: str, label: str) -> list[dict]:
    """Return direct reviewed mappings, excluding inverse-only surface labels.

    Extraction canonicalizes supported inverse predicates together with their
    endpoints before annotation. Matching inverse declarations here without
    that endpoint swap could attach a canonical IRI to the wrong direction.
    """

    key = _normalize_label(label)
    matches = []
    for entry in mapping[section]:
        direct_labels = (
            entry.get("label"),
            entry.get("preferred_label"),
            *(entry.get("aliases") or []),
        )
        if key and any(_normalize_label(value) == key for value in direct_labels):
            matches.append(entry)
    return matches


def annotate_ontology_label(label: str, *, relation: bool) -> dict[str, str]:
    """Annotate reviewed direct labels; conditional IRIs remain unasserted."""
    if not ontology_annotations_enabled():
        return {}

    default_path = (
        Path(__file__).resolve().parent.parent / "ontology" / "pem_mapping_v1.json"
    )
    path = os.environ.get("PEM_ONTOLOGY_MAPPING_PATH", str(default_path))
    mapping = _load_mapping(path, Path(path).stat().st_mtime_ns)
    section = "relations" if relation else "entity_types"
    matches = _matching_entries(mapping, section, label)
    if len(matches) > 1:
        entry = {"status": "ambiguous"}
    else:
        entry = matches[0] if matches else {"status": "unknown"}
    status = entry["status"]
    result = {
        "ontology_mapping_version": str(mapping["mapping_version"]),
        "ontology_mapping_status": status,
        "ontology_iri": "",
        "ontology_source": "",
    }
    if status == "mapped":
        result["ontology_iri"] = str(entry["iri"])
        if entry.get("source_ontology"):
            result["ontology_source"] = str(entry["source_ontology"])
    return result
