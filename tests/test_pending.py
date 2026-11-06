import json
import os
import signal
import subprocess

import pytest

from dotde import pending, restore
from dotde.profiles import load_common, load_profile
from tests.helpers import make_archive, open_archive, write


@pytest.fixture
def staged(tmp_path, home):
    src = tmp_path / "old" / "olduser"
    write(src, ".config/kwinrc", f"[X]\nImage={src}/bg.png\n".encode())
    write(src, ".config/kglobalshortcutsrc", b"[kwin]\nExpose=Ctrl+F9\n")
    write(home, ".config/kwinrc", b"[Before]\n")
    opened = open_archive(make_archive(src, tmp_path / "out", extras=()), home)
    plan = restore.build_plan(opened, load_profile("kde"), load_common(), {"windows", "shortcuts"}, home)
    pending.stage(opened, plan, home, "kde")
    opened.cleanup()
    return home


def test_stage_creates_pending_and_script(staged):
    home = staged
    assert pending.has_pending(home)
    assert pending.script_path(home).is_file()
    assert (home / ".config/kwinrc").read_bytes() == b"[Before]\n"  # nothing applied yet
    staged_kwinrc = (pending.pending_dir(home) / "files/.config/kwinrc").read_text()
    assert f"Image={home}/bg.png" in staged_kwinrc  # already rewritten


def test_stage_refuses_existing_pending(staged, tmp_path):
    with pytest.raises(FileExistsError):
        pending.stage(None, restore.RestorePlan(), staged, "kde")


def test_script_syntax_and_does_not_break_shell(staged):
    script = pending.script_path(staged)
    assert subprocess.run(["sh", "-n", str(script)]).returncode == 0
    text = script.read_text()
    assert "exit" not in text and "exec " not in text
    # sourced like plasma-sourceenv.sh does, followed by another command: the shell must go on
    out = subprocess.run(["sh", "-c", f'. "{script}" >/dev/null; echo still-alive'],
                         capture_output=True, text=True, env={**os.environ, "HOME": str(staged)})
    assert out.stdout.strip() == "still-alive"
    # end to end: the script really ran `dotde --apply-pending` and removed itself
    assert f"Image={staged}/bg.png" in (staged / ".config/kwinrc").read_text()
    assert not script.exists() and pending.last_apply(staged)["status"] == "ok"


def test_script_quotes_weird_home(tmp_path, monkeypatch):
    home = tmp_path / "home" / "d'angelo rossi"
    home.mkdir(parents=True)
    script = pending.render_script(home)
    f = tmp_path / "s.sh"
    f.write_text(script)
    assert subprocess.run(["sh", "-n", str(f)]).returncode == 0
    assert "d'\"'\"'angelo rossi" in script  # shlex-quoted


def test_apply_pending(staged):
    home = staged
    assert pending.apply_pending(home) == 0
    assert f"Image={home}/bg.png" in (home / ".config/kwinrc").read_text()
    assert (home / ".config/kglobalshortcutsrc").is_file()
    assert not pending.has_pending(home) and not pending.script_path(home).exists()
    result = pending.last_apply(home)
    assert result["status"] == "ok"
    backup = restore.latest_backup(home)
    assert (backup.dir / "files/.config/kwinrc").read_bytes() == b"[Before]\n"


def test_apply_pending_error_still_cleans_up(staged, monkeypatch):
    home = staged
    monkeypatch.setattr(pending, "apply_items", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    assert pending.apply_pending(home) == 1
    assert not pending.script_path(home).exists() and not pending.has_pending(home)
    result = pending.last_apply(home)
    assert result["status"] == "error" and "disk full" in result["message"]


def test_apply_pending_revalidates(staged):
    home = staged
    info_path = pending.pending_dir(home) / "pending.json"
    info = json.loads(info_path.read_text())
    info["items"].append({"rel": ".local/bin/evil", "member": "files/.local/bin/evil", "category": "x", "mode": 493})
    info_path.write_text(json.dumps(info))
    assert pending.apply_pending(home) == 1
    assert not (home / ".local/bin/evil").exists()


def test_apply_pending_nothing_to_do(home):
    assert pending.apply_pending(home) == 0


def test_cancel_pending(staged):
    pending.cancel_pending(staged)
    assert not pending.has_pending(staged) and not pending.script_path(staged).exists()
    assert (staged / ".config/kwinrc").read_bytes() == b"[Before]\n"


def test_last_apply_seen(staged):
    pending.apply_pending(staged)
    assert pending.last_apply(staged)["seen"] is False
    pending.mark_last_apply_seen(staged)
    assert pending.last_apply(staged)["seen"] is True


def test_deferred_undo(staged):
    home = staged
    pending.apply_pending(home)
    after_import = (home / ".config/kwinrc").read_bytes()
    pending.stage_undo(restore.latest_backup(home), home)
    assert (home / ".config/kwinrc").read_bytes() == after_import  # not yet
    pending.apply_pending(home)
    assert (home / ".config/kwinrc").read_bytes() == b"[Before]\n"
    assert not (home / ".config/kglobalshortcutsrc").exists()  # created by the import: removed


def test_ctrl_c_is_deferred_to_end_of_file(tmp_path, home):
    src = tmp_path / "src"
    items = []
    for i in range(3):
        write(src, f"files/.config/f{i}", b"data%d" % i)
        items.append(restore.PlanItem(f".config/f{i}", f"files/.config/f{i}", "x", 0o644))

    def progress(done, total):
        if done == 1:
            os.kill(os.getpid(), signal.SIGINT)

    with pytest.raises(KeyboardInterrupt):
        restore.apply_items(home, src, items, None, progress)
    assert (home / ".config/f0").read_bytes() == b"data0"
    assert not (home / ".config/f1").exists()
