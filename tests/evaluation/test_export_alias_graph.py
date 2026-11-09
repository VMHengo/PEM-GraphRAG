from unittest.mock import Mock

import pytest

from scripts.export_alias_graph import export_snapshot


def test_export_is_bounded_and_reports_truncation():
    session = Mock()
    session.run.return_value = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    snapshot = export_snapshot(session, 2)
    assert snapshot == {"truncated": True, "edges": [{"id": "a"}, {"id": "b"}]}
    assert session.run.call_args.kwargs == {"limit": 3}


def test_export_rejects_unbounded_limit():
    with pytest.raises(ValueError):
        export_snapshot(Mock(), 10001)
