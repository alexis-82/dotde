import os

from dotde import session
from dotde.profiles import load_profile


def fake_proc(tmp_path, procs):
    root = tmp_path / "proc"
    root.mkdir()
    for pid, name in procs.items():
        d = root / str(pid)
        d.mkdir()
        (d / "comm").write_text(name + "\n")
    (root / "self").mkdir()
    return root


def test_is_running(tmp_path):
    proc = fake_proc(tmp_path, {10: "plasmashell", 11: "bash"})
    assert session.is_running("plasmashell", os.getuid(), proc)
    assert not session.is_running("xfce4-session", os.getuid(), proc)


def test_other_user_ignored(tmp_path):
    proc = fake_proc(tmp_path, {10: "plasmashell"})
    assert not session.is_running("plasmashell", os.getuid() + 1, proc)


def test_comm_truncated(tmp_path):
    proc = fake_proc(tmp_path, {10: "xfce4-panel-plu"})  # 15 chars
    assert session.is_running("xfce4-panel-plugin", os.getuid(), proc)


def test_choose_mode():
    kde, xfce, gnome = load_profile("kde"), load_profile("xfce"), load_profile("gnome")
    assert session.choose_mode(kde, True) == "deferred"
    assert session.choose_mode(kde, False) == "immediate"
    assert session.choose_mode(xfce, True) == "offline"
    assert session.choose_mode(gnome, True) == "immediate"
    assert session.choose_mode(None, True) == "immediate"


def test_logout_command(monkeypatch):
    kde = load_profile("kde")
    monkeypatch.setattr(session.shutil, "which", lambda c: f"/usr/bin/{c}")
    assert session.logout_command(kde) == ["qdbus6", "org.kde.Shutdown", "/Shutdown", "logout"]
    monkeypatch.setattr(session.shutil, "which", lambda c: "/usr/bin/loginctl" if c == "loginctl" else None)
    monkeypatch.setenv("XDG_SESSION_ID", "3")
    assert session.logout_command(kde) == ["loginctl", "terminate-session", "3"]
    monkeypatch.delenv("XDG_SESSION_ID")
    assert session.logout_command(kde) is None
