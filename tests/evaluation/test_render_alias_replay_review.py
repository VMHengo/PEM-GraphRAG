import pytest

from scripts.render_alias_replay_review import render


def test_render_embeds_data_without_executable_script_breakout():
    page = render({"additional_paths": [{"hops": [{"description": "</script><script>alert(1)</script>"}]}]})
    assert "\\u003c/script\\u003e" in page
    assert "</script><script>alert(1)" not in page
    assert "Export reviews" in page


def test_render_rejects_wrong_input():
    with pytest.raises(ValueError):
        render({"edges": []})


def test_render_preloads_private_reviews():
    page = render({"additional_paths": []}, {"reviews": {"edge-1": {"verdict": "uncertain"}}})
    assert '"edge-1": {"verdict": "uncertain"}' in page
