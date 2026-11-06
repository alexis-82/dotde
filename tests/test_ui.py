"""UI flows with scripted answers (no terminal needed)."""

import json

import pytest

from dotde import pending, ui
from dotde.detect import Distro, Environment
from tests.helpers import make_archive, write


class Script:
    """Replaces ui.ask: returns the next scripted answer for each question."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.asked = []

    def __call__(self, question):
        self.asked.append(question)
        if not self.answers:
            raise AssertionError("unexpected extra question")
        answer = self.answers.pop(0)
        if answer is ui.Cancelled:
            raise ui.Cancelled
        return answer


@pytest.fixture
def out(monkeypatch):
    printed = []
    monkeypatch.setattr(ui.console, "print", lambda *a, **k: printed.append(" ".join(str(x) for x in a)))
    return printed


def snapshot(home):
    rels = (str(p.relative_to(home)) for p in home.rglob("*"))
    return sorted(r for r in rels if not ".local/state/dotde/".startswith(r + "/") and ".local/state" not in r)


@pytest.mark.parametrize("lang, expected", [("it_IT.UTF-8", "Ctrl+Alt+F3"), ("en_US.UTF-8", "Ctrl+Alt+F3")])
def test_offline_import_writes_nothing(tmp_path, home, monkeypatch, out, lang, expected):
    monkeypatch.setenv("LANG", lang)
    monkeypatch.delenv("LC_ALL", raising=False)
    src = tmp_path / "old" / "olduser"
    write(src, ".config/xfce4/panel/whiskermenu-1.rc", b"x=1\n")
    archive = make_archive(src, tmp_path / "out", de="xfce", categories=("panel",), extras=(), packages={})
    monkeypatch.setattr(ui, "is_running", lambda name: name == "xfce4-session")
    before = snapshot(home)
    monkeypatch.setattr(ui, "ask", Script(str(archive), {"panel"}))  # path, categories
    env = Environment(Distro("cachyos", ["arch"], "CachyOS", "arch"), "xfce", "XFCE", "x11")
    ui.flow_import(env)
    assert snapshot(home) == before
    assert any(expected in line for line in out)
    assert not any((home / ".local/state/dotde/tmp").glob("import-*"))  # work folder cleaned


def test_last_apply_error_shown_once(home, out):
    p = pending.last_apply_path(home)
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"status": "error", "message": "disk full", "seen": False}))
    env = Environment(Distro(pretty_name="X"), "kde", "KDE", "wayland")
    ui.show_header(env, None, "")
    assert any("disk full" in line for line in out)
    out.clear()
    ui.show_header(env, None, "")
    assert not any("disk full" in line for line in out)


def test_unknown_de_asks_for_profile(home, monkeypatch, out):
    monkeypatch.setattr(ui, "ask", Script("gnome"))
    env = Environment(Distro(), "unknown", "X-Cinnamon", "x11")
    assert ui.pick_profile(env).id == "gnome"
    monkeypatch.setattr(ui, "ask", Script(""))
    assert ui.pick_profile(env) is None  # common settings only


def test_export_cancel_before_confirm_writes_nothing(tmp_path, home, monkeypatch, out):
    write(home, ".config/kwinrc", b"[X]\n")
    dest = tmp_path / "dest"
    # categories, destination, confirm = no (no extra apps and no package sources are offered)
    script = Script(["windows"], str(dest), False)
    monkeypatch.setattr(ui, "ask", script)
    monkeypatch.setattr(ui, "source_available", lambda s: False)
    env = Environment(Distro("cachyos", ["arch"], "CachyOS", "arch"), "kde", "KDE", "wayland")
    with pytest.raises(ui.Cancelled):
        ui.flow_export(env)
    assert not dest.exists() or not any(dest.iterdir())


def test_export_writes_archive(tmp_path, home, monkeypatch, out):
    write(home, ".config/kwinrc", b"[X]\n")
    dest = tmp_path / "dest"
    monkeypatch.setattr(ui, "ask", Script(["windows"], str(dest), True))
    monkeypatch.setattr(ui, "source_available", lambda s: False)
    env = Environment(Distro("cachyos", ["arch"], "CachyOS", "arch"), "kde", "KDE", "wayland")
    ui.flow_export(env)
    assert len(list(dest.glob("dotde-kde-*.tar.gz"))) == 1


def test_main_menu_ctrl_c_exits(home, monkeypatch, out):
    monkeypatch.setattr(ui, "ask", Script(ui.Cancelled))
    monkeypatch.setattr(ui, "detect_environment", lambda: Environment(Distro(), "unknown", "", "tty"))
    assert ui.run() == 0


def test_arrows_stop_at_the_ends():
    import questionary
    from questionary.prompts.common import InquirerControl

    choices = [
        questionary.Choice("a", "a"),
        questionary.Choice("b", "b"),
        questionary.Choice("disabled", "d", disabled="x"),
        questionary.Separator(" "),
        questionary.Choice("exit", "e"),
    ]
    ic = InquirerControl(choices)
    assert ic.pointed_at == 0
    ic.select_previous()
    assert ic.pointed_at == 0  # top: stays
    ic.select_next()
    assert ic.pointed_at == 1
    ic.select_next()
    assert ic.pointed_at == 4  # skips disabled item and separator
    ic.select_next()
    assert ic.pointed_at == 4  # bottom: stays
    ic.select_previous()
    assert ic.pointed_at == 1


def test_ctrl_c_during_an_operation_returns_to_menu(home, monkeypatch, out):
    def busy(env):
        raise KeyboardInterrupt  # e.g. Ctrl+C while files are collected

    monkeypatch.setattr(ui, "flow_export", busy)
    monkeypatch.setattr(ui, "ask", Script("export", ui.Cancelled))  # export, then leave the menu
    monkeypatch.setattr(ui, "detect_environment", lambda: Environment(Distro(), "unknown", "", "tty"))
    assert ui.run() == 0
    assert any("Cancelled" in line or "Annullato" in line for line in out)
