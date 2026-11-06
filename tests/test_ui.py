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


def _run_with_keys(question, keys):
    from prompt_toolkit.input import create_pipe_input
    from prompt_toolkit.output import DummyOutput

    with create_pipe_input() as pipe:
        question.application.input = pipe
        question.application.output = DummyOutput()
        pipe.send_text(keys)
        return question.unsafe_ask()


def test_checkbox_back_entry_with_enter():
    import questionary
    q = ui.checkbox("pick", [questionary.Choice("a", "a"), questionary.Choice("b", "b")], back=True)
    assert _run_with_keys(q, "\x1b[B\x1b[B\r") == ui.BACK  # down, down (skips the empty line), enter


def test_checkbox_space_on_back_does_nothing_and_enter_on_item_submits():
    import questionary
    q = ui.checkbox("pick", [questionary.Choice("a", "a"), questionary.Choice("b", "b")], back=True)
    # tick "a", go to Back and press space (ignored), go up to "b", submit
    assert _run_with_keys(q, " \x1b[B\x1b[B \x1b[A\r") == ["a"]


def test_select_has_back_after_an_empty_line():
    import questionary
    q = ui.select("pick", [questionary.Choice("a", "a")], back=True)
    control = next(c for c in q.application.layout.find_all_controls() if isinstance(c, ui.InquirerControl))
    assert isinstance(control.choices[-2], questionary.Separator)
    assert control.choices[-1].value == ui.BACK
    assert _run_with_keys(q, "\x1b[B\r") == ui.BACK


def test_export_steps_back_keeps_previous_answers(monkeypatch):
    from types import SimpleNamespace
    cats = [SimpleNamespace(id="windows", label={"en": "W"}, profile="kde"),
            SimpleNamespace(id="gtk", label={"en": "G"}, profile="common")]
    candidates = [SimpleNamespace(name="fish", size=10, sensitive=False)]
    sources = [("native", "pacman", "Packages (pacman)")]
    script = Script(["windows"], ui.BACK, ["windows", "gtk"], ["fish"], ui.BACK, ["fish"], ["native"])
    monkeypatch.setattr(ui, "ask", script)
    assert ui.choose_export(cats, candidates, sources) == (["windows", "gtk"], ["fish"], ["native"])

    def checked(question):
        control = next(c for c in question.application.layout.find_all_controls()
                       if isinstance(c, ui.InquirerControl))
        return control.selected_options

    assert checked(script.asked[2]) == ["windows"]  # back to step 1: previous ticks kept
    assert checked(script.asked[5]) == ["fish"]


def test_back_on_first_step_returns_to_menu(monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(ui, "ask", Script(ui.BACK))
    with pytest.raises(ui.GoBack):
        ui.choose_export([SimpleNamespace(id="w", label={"en": "W"}, profile="kde")], [], [])


def test_go_back_skips_the_pause(home, monkeypatch, out):
    def flow(env):
        raise ui.GoBack

    paused = []
    monkeypatch.setattr(ui, "flow_export", flow)
    monkeypatch.setattr(ui, "pause", lambda: paused.append(1))
    monkeypatch.setattr(ui, "ask", Script("export", ui.Cancelled))
    monkeypatch.setattr(ui, "detect_environment", lambda: Environment(Distro(), "unknown", "", "tty"))
    assert ui.run() == 0 and paused == []


def test_back_entry_has_no_tick_box():
    import questionary
    q = ui.checkbox("pick", [questionary.Choice("a", "a")], back=True)
    control = next(c for c in q.application.layout.find_all_controls() if isinstance(c, ui.InquirerControl))
    text = "".join(t[1] for t in control._get_choice_tokens())
    lines = text.split("\n")
    assert "○" in lines[0]  # normal item keeps its box
    back_line = next(line for line in lines if "Indietro" in line or "Back" in line)
    assert "○" not in back_line and "●" not in back_line
