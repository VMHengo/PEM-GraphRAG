"""Conservative, opt-in PEM ontology annotations for graph properties."""

from __future__ import annotations

import json
import os
import hashlib
from functools import lru_cache
from pathlib import Path


def ontology_annotations_enabled() -> bool:
    return os.environ.get("ONTOLOGY_ANNOTATION_ENABLED", "false").lower() in {
        "1", "true", "yes", "on"
    }


def ontology_annotation_revision() -> dict[str, str | bool]:
    if not ontology_annotations_enabled():
        return {"enabled": False}
    path = os.environ.get(
        "PEM_ONTOLOGY_MAPPING_PATH",
        str(Path(__file__).resolve().parent.parent / "ontology" / "pem_mapping_v1.json"),
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
    return mapping


def annotate_ontology_label(label: str, *, relation: bool) -> dict[str, str]:
    """Annotate only exact reviewed labels; conditional IRIs remain unasserted."""
    if not ontology_annotations_enabled():
        return {}

    default_path = Path(__file__).resolve().parent.parent / "ontology" / "pem_mapping_v1.json"
    path = os.environ.get("PEM_ONTOLOGY_MAPPING_PATH", str(default_path))
    mapping = _load_mapping(path, Path(path).stat().st_mtime_ns)
    section = "relations" if relation else "entity_types"
    matches = [
        item for item in mapping[section]
        if item.get("label", "").casefold() == label.strip().casefold()
    ]
    if len(matches) > 1:
        raise ValueError(f"Duplicate ontology mapping for {section}: {label}")
    entry = matches[0] if matches else {"status": "unmapped"}
    status = entry["status"]
    result = {
        "ontology_mapping_version": str(mapping["mapping_version"]),
        "ontology_mapping_status": status,
        "ontology_iri": "",
        "ontology_source": "",
    }
    if status == "mapped":
        iri = entry.get("iri")
        if not iri:
            raise ValueError(f"Mapped ontology label has no IRI: {label}")
        result["ontology_iri"] = iri
        if entry.get("source_ontology"):
            result["ontology_source"] = entry["source_ontology"]
    return result
