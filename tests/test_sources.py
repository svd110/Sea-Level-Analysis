import pytest

from slr import sources


@pytest.fixture
def snapshot_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(sources, "SNAPSHOT_DIR", tmp_path)
    return tmp_path


def _fail():
    raise sources.SourceError("offline")


def test_live_fetch_is_marked_live(snapshot_dir):
    f = sources._with_snapshot("x", "Test", lambda: [1, 2])
    assert f.source == "live" and f.data == [1, 2]


def test_failed_fetch_falls_back_to_snapshot(snapshot_dir):
    sources.save_snapshot("x", [3])
    f = sources._with_snapshot("x", "Test", _fail)
    assert f.source == "snapshot" and f.data == [3]


def test_failed_fetch_without_snapshot_raises(snapshot_dir):
    with pytest.raises(sources.SourceError):
        sources._with_snapshot("missing", "Test", _fail)


def test_gmsl_tries_providers_in_order_then_snapshot(snapshot_dir, monkeypatch):
    sources.save_snapshot("gmsl", [[1993.0, 0.0]])
    monkeypatch.setattr(sources, "GMSL_PROVIDERS", (("A", _fail), ("B", lambda: [[2000.0, 1.0]])))
    assert sources.load_gmsl().origin == "B"
    monkeypatch.setattr(sources, "GMSL_PROVIDERS", (("A", _fail), ("B", _fail)))
    f = sources.load_gmsl()
    assert f.source == "snapshot" and f.data == [[1993.0, 0.0]]
