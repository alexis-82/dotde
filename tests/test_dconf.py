import subprocess

import pytest

from dotde import dconf


class FakeRun:
    def __init__(self, stdout="", returncode=0):
        self.calls = []
        self.stdout, self.returncode = stdout, returncode

    def __call__(self, cmd, **kw):
        self.calls.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, self.returncode, self.stdout, "boom")


def test_dump(monkeypatch):
    fake = FakeRun("[/]\ncolor-scheme='prefer-dark'\n")
    monkeypatch.setattr(subprocess, "run", fake)
    assert "prefer-dark" in dconf.dump("/org/gnome/desktop/interface/")
    assert fake.calls[0][0] == ["dconf", "dump", "/org/gnome/desktop/interface/"]


def test_dump_error(monkeypatch):
    monkeypatch.setattr(subprocess, "run", FakeRun(returncode=1))
    with pytest.raises(dconf.DconfError):
        dconf.dump("/x/")


def test_not_available(monkeypatch):
    monkeypatch.setattr(dconf.shutil, "which", lambda _: None)
    assert not dconf.available()
    assert not dconf.can_load()


def test_bus_from_socket(monkeypatch, tmp_path):
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.setattr(dconf, "Path", lambda p: tmp_path / "bus")
    (tmp_path / "bus").touch()
    fake = FakeRun()
    monkeypatch.setattr(subprocess, "run", fake)
    dconf.load("/x/", "[/]\na=1\n")
    env = fake.calls[0][1]["env"]
    assert env["DBUS_SESSION_BUS_ADDRESS"] == f"unix:path={tmp_path / 'bus'}"
    assert fake.calls[0][1]["input"] == "[/]\na=1\n"


def test_no_bus_no_socket(monkeypatch, tmp_path):
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    monkeypatch.setattr(dconf, "Path", lambda p: tmp_path / "missing")
    monkeypatch.setattr(dconf.shutil, "which", lambda _: "/usr/bin/dconf")
    assert not dconf.can_load()
