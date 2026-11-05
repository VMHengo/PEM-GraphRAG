"""Compare v2 and v3 on the same two aging-paper chunks in Staging.

The API key stays inside the container environment. No candidate is promoted.
"""

from __future__ import annotations

import argparse
import json
import os
from urllib.error import HTTPError
from urllib.request import Request, urlopen

BASE = "http://127.0.0.1:9621/evaluation/prompt-experiments"
DOC_ID = "doc-1c985b11ca48c9796d50febb7eaca9ea"
BENCHMARK_ID = "pem_high_temperature_aging_evidence_benchmark"
BASELINE = "pem_aging_explicit_intermediates_v2.yml"
VARIANT = "pem_explicit_causal_bridge_v3.yml"
BASELINE_SHA = "8a610991743cf04073d76983d51e75f38710836ea76319fd2ad1b0b388c21546"
VARIANT_SHA = "42f67d65d6976e095bfe6a73b425825cca1570a792e3797eec5af1f031497bf7"
CHUNK_IDS = [f"{DOC_ID}-chunk-{number:03d}" for number in (3, 6)]


def request_json(method: str, path: str, payload: dict | None = None) -> dict:
    key = os.environ["LIGHTRAG_API_KEY"]
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(
        BASE + path,
        data=data,
        headers={"X-API-Key": key, "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urlopen(request, timeout=90) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"{method} {path}: HTTP {exc.code}: {exc.read(1000)!r}") from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", action="store_true", help="Start after estimate and safety checks")
    parser.add_argument("--poll", metavar="EXPERIMENT_ID", help="Report existing experiment status")
    parser.add_argument("--max-estimated-usd", type=float, default=1.0)
    args = parser.parse_args()

    if args.poll:
        experiment = request_json("GET", f"/{args.poll}")
        print(json.dumps({
            "id": experiment.get("id"),
            "status": experiment.get("status"),
            "error": experiment.get("error"),
            "candidates": [
                {
                    "profile_file": item.get("profile_file"),
                    "status": item.get("status"),
                    "error": item.get("error"),
                    "scores": item.get("scores"),
                    "extraction_cache_snapshot": item.get("extraction_cache_snapshot"),
                }
                for item in experiment.get("candidates", [])
            ],
        }, indent=2))
        return

    config = request_json("GET", "/config")
    if not config.get("enabled"):
        raise SystemExit("Prompt experiments are disabled")
    profiles = {item["file"]: item for item in config.get("profiles", [])}
    if profiles.get(BASELINE, {}).get("fingerprint") != BASELINE_SHA:
        raise SystemExit("Staging baseline fingerprint changed; refusing to compare")
    if profiles.get(VARIANT, {}).get("fingerprint") != VARIANT_SHA:
        raise SystemExit("Staging variant fingerprint changed or profile is missing")

    current = request_json("GET", "?limit=5")
    if any(item.get("status") in {"queued", "running"} for item in current.get("experiments", [])):
        raise SystemExit("Another prompt experiment is queued or running")

    payload = {
        "document_ids": [DOC_ID],
        "profile_files": [BASELINE, VARIANT],
        "optimization_mode": "validation",
        "benchmark_id": BENCHMARK_ID,
        "selected_chunk_ids": CHUNK_IDS,
    }
    estimate = request_json("POST", "/estimate", payload)
    print(json.dumps({
        "selected_documents": estimate.get("selected_documents"),
        "selected_chunks": estimate.get("selected_chunks"),
        "estimated_llm_calls": estimate.get("estimated_llm_calls"),
        "estimated_cost_usd_extraction_only": estimate.get("estimated_cost_usd"),
        "benchmark_preflight": estimate.get("benchmark_preflight"),
        "profiles": [
            {"file": item["file"], "fingerprint": item["fingerprint"]}
            for item in (profiles[BASELINE], profiles[VARIANT])
        ],
    }, indent=2))

    if estimate.get("selected_documents") != 1 or estimate.get("selected_chunks") != 2:
        raise SystemExit("Unexpected document or chunk scope; refusing to start")
    preflight = estimate.get("benchmark_preflight") or {}
    if not preflight.get("compatible"):
        raise SystemExit("Benchmark source scope is incompatible")
    cost = estimate.get("estimated_cost_usd")
    if not isinstance(cost, (int, float)) or cost > args.max_estimated_usd:
        raise SystemExit("Extraction estimate exceeds safety cap")

    if args.start:
        started = request_json("POST", "", {
            **payload,
            "title": "Aging causal bridge v2 vs v3 (two chunks)",
            "note": "Isolated chunks 003 and 006 only. Benchmark totals are incomplete-document diagnostics, not comparable to ten-chunk runs. Do not promote.",
        })
        print(json.dumps({"experiment_id": started.get("id"), "status": started.get("status")}))


if __name__ == "__main__":
    main()
