"""Select a deterministic, diverse offline alias-path review sample."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
import random


def _bridge(path: dict) -> str:
    for left, right in zip(path["hops"], path["hops"][1:]):
        if left["target"] != right["source"]:
            return " / ".join(sorted((left["target"], right["source"])))
    return "unknown"


def select_sample(result: dict, *, seed: int = 20261109, mixed: int = 14, other: int = 6) -> dict:
    paths = result.get("additional_paths")
    if not isinstance(paths, list) or mixed < 0 or other < 0 or mixed + other > 20:
        raise ValueError("Expected paths and at most 20 review cases")
    rng = random.Random(seed)
    selected: list[dict] = []
    used_edges: set[str] = set()
    used_endpoints: set[tuple[str, str]] = set()

    for category, quota in (("mixed", mixed), ("other", other)):
        groups: dict[str, list[dict]] = defaultdict(list)
        for path in paths:
            if path.get("causal_only"):
                continue
            if ("mixed" if path.get("mixed_causal") else "other") == category:
                groups[_bridge(path)].append(path)
        for group in groups.values():
            rng.shuffle(group)
        while quota and any(groups.values()):
            choices = []
            for bridge, group in groups.items():
                for path in group:
                    edge_ids = {str(hop["id"]) for hop in path["hops"]}
                    endpoints = (path["hops"][0]["source"], path["hops"][-1]["target"])
                    score = (
                        sum(hop in used_edges for hop in edge_ids),
                        endpoints in used_endpoints,
                        sum(_bridge(item) == bridge for item in selected),
                        len(path["hops"]),
                    )
                    choices.append((score, rng.random(), bridge, path))
            _, _, bridge, chosen = min(choices, key=lambda item: (item[0], item[1]))
            groups[bridge].remove(chosen)
            selected.append(chosen)
            used_edges.update(str(hop["id"]) for hop in chosen["hops"])
            used_endpoints.add((chosen["hops"][0]["source"], chosen["hops"][-1]["target"]))
            quota -= 1
    return {
        **{key: value for key, value in result.items() if key not in (
            "additional_paths", "causal_additional_paths", "mixed_additional_paths")},
        "sample": {"seed": seed, "requested_mixed": mixed, "requested_other": other,
                   "selected": len(selected), "method": "bridge-stratified, edge-diverse"},
        "additional_paths": selected,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("result", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seed", type=int, default=20261109)
    args = parser.parse_args()
    sample = select_sample(json.loads(args.result.read_text(encoding="utf-8")), seed=args.seed)
    args.output.write_text(json.dumps(sample, indent=2, ensure_ascii=False), encoding="utf-8")
    print(sample["sample"])


if __name__ == "__main__":
    main()
