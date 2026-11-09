import pytest

from scripts.sample_alias_paths import select_sample


def path(index, bridge, mixed=True):
    return {
        "mixed_causal": mixed,
        "causal_only": False,
        "hops": [
            {"id": f"in-{index}", "source": f"Start {index}", "target": bridge},
            {"id": f"out-{index}", "source": bridge + "s", "target": f"End {index}"},
        ],
    }


def test_sample_is_reproducible_and_stratified():
    result = {"additional_paths": [path(i, "Model" if i < 10 else "Cell") for i in range(20)]
              + [path(i, "Pack", False) for i in range(20, 30)]}
    first = select_sample(result)
    assert first == select_sample(result)
    assert len(first["additional_paths"]) == 20
    assert sum(item["mixed_causal"] for item in first["additional_paths"]) == 14
    assert {_path["hops"][0]["target"] for _path in first["additional_paths"]} == {"Model", "Cell", "Pack"}


def test_sample_rejects_more_than_review_limit():
    with pytest.raises(ValueError):
        select_sample({"additional_paths": []}, mixed=21)
