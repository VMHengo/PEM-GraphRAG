"""Run the bounded aging-paper prompt comparison from inside Staging LightRAG.

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
BASELINE = "pem_aging_baseline_20261104.yml"
VARIANT = "pem_aging_signed_states_v1.yml"
BASELINE_SHA = "c149a623ec855eb8a65a5362fdefeb5ba1dc2a0c12bb410cc3bcc71a7f49a497"


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
    if VARIANT not in profiles:
        raise SystemExit("Staging variant profile is missing or invalid")

    current = request_json("GET", "?limit=5")
    if any(item.get("status") in {"queued", "running"} for item in current.get("experiments", [])):
        raise SystemExit("Another prompt experiment is queued or running")

    payload = {
        "document_ids": [DOC_ID],
        "profile_files": [BASELINE, VARIANT],
        "optimization_mode": "validation",
        "benchmark_id": BENCHMARK_ID,
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

    if estimate.get("selected_documents") != 1 or estimate.get("selected_chunks") != 10:
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
            "title": "Aging signed-state prompt A/B 2026-11-04",
            "note": "Isolated 10-chunk Validation; baseline snapshot versus state/sign/evidence variant. Do not promote without source review.",
        })
        print(json.dumps({"experiment_id": started.get("id"), "status": started.get("status")}))


if __name__ == "__main__":
    main()
