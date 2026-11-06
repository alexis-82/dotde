import pytest


@pytest.fixture
def home(tmp_path, monkeypatch):
    """A fake home directory: tests never touch the real one."""
    h = tmp_path / "home" / "tester"
    h.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(h))
    return h
