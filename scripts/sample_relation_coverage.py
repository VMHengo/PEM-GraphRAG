"""Draw a reproducible, private sample of PDF passages for relation review."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
from pathlib import Path

from pypdf import PdfReader


SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")
REFERENCE_HEADING = re.compile(r"(?im)^\s*(?:references|bibliography)\s*$")


def candidates(path: Path, *, max_pages: int) -> list[dict[str, object]]:
    result = []
    for page_number, page in enumerate(PdfReader(path).pages[:max_pages], 1):
        text = page.extract_text() or ""
        heading = REFERENCE_HEADING.search(text)
        if heading:
            text = text[: heading.start()]
        normalized = re.sub(r"\s+", " ", text).strip()
        passages = SENTENCE_BOUNDARY.split(normalized)
        for passage_number, passage in enumerate(passages):
            passage = passage.strip()
            if 80 <= len(passage) <= 800 and len(passage.split()) >= 12:
                result.append({
                    "page": page_number,
                    "passage_number": passage_number,
                    "text": passage,
                    "context_before": passages[passage_number - 1].strip()[-500:]
                    if passage_number else "",
                    "context_after": passages[passage_number + 1].strip()[:500]
                    if passage_number + 1 < len(passages) else "",
                })
        if heading:
            break
    return result


def sample_documents(
    paths: list[Path], *, seed: int, per_document: int, max_pages: int
) -> dict[str, object]:
    if per_document < 1 or max_pages < 1:
        raise ValueError("per_document and max_pages must be positive")
    documents = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(path)
        pool = candidates(path, max_pages=max_pages)
        if len(pool) < per_document:
            raise ValueError(f"Only {len(pool)} eligible passages in {path.name}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        rng = random.Random(f"{seed}:{digest}")
        selected = rng.sample(pool, per_document)
        documents.append({
            "file_name": path.name,
            "sha256": digest,
            "eligible_passages": len(pool),
            "sample": [
                {
                    "id": f"{digest[:12]}:p{item['page']:03d}:s{item['passage_number']:03d}",
                    **item,
                    "review": {
                        "eligible_fact": None,
                        "gold_assertions": [],
                        "notes": "",
                    },
                }
                for item in sorted(selected, key=lambda item: (item["page"], item["passage_number"]))
            ],
        })
    return {
        "schema_version": 1,
        "seed": seed,
        "per_document": per_document,
        "max_pages": max_pages,
        "documents": documents,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("pdfs", nargs="+", type=Path)
    parser.add_argument("--seed", type=int, default=20261106)
    parser.add_argument("--per-document", type=int, default=12)
    parser.add_argument("--max-pages", type=int, default=8)
    args = parser.parse_args()
    result = sample_documents(
        args.pdfs, seed=args.seed, per_document=args.per_document,
        max_pages=args.max_pages,
    )
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(result['documents'])} documents to {args.output}")


if __name__ == "__main__":
    main()
