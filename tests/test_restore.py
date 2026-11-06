import json
import os

import pytest

from dotde import restore
from dotde.archive import read_archive
from dotde.profiles import load_common, load_profile
from tests.helpers import env, make_archive, open_archive, write


@pytest.fixture
def src_home(tmp_path):
    h = tmp_path / "old" / "olduser"
    write(h, ".config/kwinrc", f"[Wallpaper]\nImage={h}/Pictures/bg.png\nOther=/home/olduserX/no\n".encode())
    write(h, ".config/kglobalshortcutsrc", b"[kwin]\nExpose=Ctrl+F9\n")
    write(h, ".config/fish/config.fish", b"set -x EDITOR micro\n")
    write(h, ".local/share/kwin/scripts/s/blob.bin", b"\x00\x01\x02" + str(h).encode())
    return h


def everything(opened):
    return {c["id"] for c in opened.manifest["categories"]}


# --- Task 21 -------------------------------------------------------------------------------------

def test_profile_from_manifest_not_from_environment(src_home, tmp_path, home, monkeypatch):
    monkeypatch.delenv("XDG_CURRENT_DESKTOP", raising=False)
    opened = open_archive(make_archive(src_home, tmp_path / "out"), home)
    profile, notices = restore.profile_from_manifest(opened.manifest)
    assert profile.id == "kde" and not notices


def test_unknown_profile(src_home, tmp_path, home):
    opened = open_archive(make_archive(src_home, tmp_path / "out"), home)
    opened.manifest["de"]["id"] = "cinnamon"
    profile, notices = restore.profile_from_manifest(opened.manifest)
    assert profile is None and notices[0].key == "warn.unknown_profile"


def test_compatibility_notices(src_home, tmp_path, home, monkeypatch):
    monkeypatch.setenv("USER", "tester")
    monkeypatch.setattr(restore, "running_de", lambda: "")
    opened = open_archive(make_archive(src_home, tmp_path / "out"), home)
    keys = lambda n: {x.key for x in n}  # noqa: E731
    kde = load_profile("kde")
    assert keys(restore.compatibility(opened.manifest, env("gnome", "debian"), kde, home, "5.27.0")) == {
        "warn.de_differs", "warn.de_major", "warn.distro_family", "info.home_rewrite", "warn.other_origin"}
    same = restore.compatibility(opened.manifest, env("kde", "arch"), kde, home, "6.2.0")
    assert keys(same) == {"info.home_rewrite", "warn.other_origin"}


# --- Task 22 -------------------------------------------------------------------------------------

def test_plan_ignores_files_outside_profile(src_home, tmp_path, home):
    opened = open_archive(make_archive(src_home, tmp_path / "out"), home)
    # simulate a manipulated manifest: entries that are not part of their category
    opened.manifest["files"] += [
        {"path": ".local/bin/ls", "category": "windows", "sha256": "", "mode": 0o755},
        {"path": ".local/state/dotde/x", "category": "windows", "sha256": ""},
        {"path": ".config/kdeglobals", "category": "windows", "sha256": ""},
        {"path": ".config/autostart/evil.desktop", "category": "extra:fish", "sha256": ""},
    ]
    common = load_common()
    plan = restore.build_plan(opened, load_profile("kde"), common, everything(opened), home)
    ignored = dict(plan.ignored)
    assert ignored[".local/bin/ls"] == "forbidden_path"
    assert ignored[".local/state/dotde/x"] == "forbidden_path"
    assert ignored[".config/kdeglobals"] == "outside_category"
    assert ignored[".config/autostart/evil.desktop"] == "outside_category"
    assert {i.rel for i in plan.items} == {
        ".config/kwinrc", ".config/kglobalshortcutsrc", ".config/fish/config.fish", ".local/share/kwin/scripts/s/blob.bin"}
    assert plan.extras == ["fish"]


def test_plan_lists_autostart(tmp_path, home):
    src = tmp_path / "old" / "olduser"
    write(src, ".config/autostart/app.desktop", b"[Desktop Entry]\nExec=app\n")
    opened = open_archive(make_archive(src, tmp_path / "out", categories=("autostart",), extras=()), home)
    plan = restore.build_plan(opened, load_profile("kde"), load_common(), everything(opened), home)
    assert plan.autostart == [".config/autostart/app.desktop"]


def test_plan_respects_selection(src_home, tmp_path, home):
    opened = open_archive(make_archive(src_home, tmp_path / "out"), home)
    plan = restore.build_plan(opened, load_profile("kde"), load_common(), {"shortcuts"}, home)
    assert [i.rel for i in plan.items] == [".config/kglobalshortcutsrc"]


# --- Task 23/24 ----------------------------------------------------------------------------------

def test_immediate_restore_with_backup_and_rewrite(src_home, tmp_path, home):
    write(home, ".config/kwinrc", b"[Old]\nmine=1\n")
    opened = open_archive(make_archive(src_home, tmp_path / "out"), home)
    plan = restore.build_plan(opened, load_profile("kde"), load_common(), everything(opened), home)
    backup, failed = restore.restore_immediate(opened, plan, home, "kde")
    assert not failed
    kwinrc = (home / ".config/kwinrc").read_text()
    assert f"Image={home}/Pictures/bg.png" in kwinrc
    assert str(src_home) not in kwinrc and "/home/olduserX/no" in kwinrc
    blob = (home / ".local/share/kwin/scripts/s/blob.bin").read_bytes()
    assert blob == b"\x00\x01\x02" + str(src_home).encode()  # binary: untouched
    assert (backup.dir / "files/.config/kwinrc").read_bytes() == b"[Old]\nmine=1\n"
    data = json.loads((backup.dir / "backup.json").read_text())
    assert data["status"] == "complete"
    assert data["overwritten"] == [".config/kwinrc"]
    assert ".config/fish/config.fish" in data["created_files"]


def test_interrupted_restore_leaves_journal(src_home, tmp_path, home, monkeypatch):
    opened = open_archive(make_archive(src_home, tmp_path / "out"), home)
    plan = restore.build_plan(opened, load_profile("kde"), load_common(), everything(opened), home)
    calls = {"n": 0}
    real = restore.atomic_write

    def flaky(path, data, mode=None):
        if path.name != "backup.json":
            calls["n"] += 1
            if calls["n"] == 2:
                raise KeyboardInterrupt
        return real(path, data, mode)

    monkeypatch.setattr(restore, "atomic_write", flaky)
    with pytest.raises(KeyboardInterrupt):
        restore.restore_immediate(opened, plan, home, "kde")
    backup = restore.latest_backup(home)
    assert backup.data["status"] == "in_progress"
    assert len(backup.data["overwritten"]) + len(backup.data["created_files"]) == len(plan.items)


def test_keep_three_backups(home):
    root = home / ".local/state/dotde"
    for i in range(4):
        (root / f"backup-2026010{i}-000000").mkdir(parents=True)
    restore.prune_backups(home)
    assert [p.name for p in restore.list_backups(home)] == [
        "backup-20260101-000000", "backup-20260102-000000", "backup-20260103-000000"]


# --- Task 25 -------------------------------------------------------------------------------------

def test_dconf_backup_then_load(tmp_path, home, monkeypatch):
    src = tmp_path / "old" / "olduser"
    calls = []
    monkeypatch.setattr(restore.dconf, "dump", lambda p: calls.append(("dump", p)) or "[/]\nold=1\n")
    monkeypatch.setattr(restore.dconf, "load", lambda p, d: calls.append(("load", p, d)))
    monkeypatch.setattr(restore.dconf, "can_load", lambda: True)
    dump = ("appearance", "/org/gnome/desktop/interface/", f"[/]\npicture-uri='file://{src}/bg.png'\n")
    opened = open_archive(make_archive(src, tmp_path / "out", de="gnome", categories=("appearance",), extras=(),
                                       dumps=[dump]), home)
    plan = restore.build_plan(opened, load_profile("gnome"), load_common(), everything(opened), home)
    restore.restore_immediate(opened, plan, home, "gnome")
    assert calls[0] == ("dump", "/org/gnome/desktop/interface/")
    assert calls[1] == ("load", "/org/gnome/desktop/interface/", f"[/]\npicture-uri='file://{home}/bg.png'\n")


# --- Task 26 -------------------------------------------------------------------------------------

def test_package_actions(src_home, tmp_path, home, monkeypatch):
    from dotde.packages import Package, PackageList
    monkeypatch.setattr(restore.shutil, "which", lambda c: None)
    monkeypatch.setattr(restore, "aur_helper", lambda: "")
    monkeypatch.setattr(restore, "split_available", lambda pl: (pl, []))
    pkgs = {"native": PackageList("pacman", [Package("firefox")]), "aur": PackageList("aur", [Package("paru-bin")])}
    opened = open_archive(make_archive(src_home, tmp_path / "out", packages=pkgs), home)
    acts = {a.key: a for a in restore.package_actions(opened, env("kde", "arch"))}
    assert acts["native"].commands == [["sudo", "pacman", "-S", "--needed", "--", "firefox"]]
    assert acts["aur"].commands == [] and acts["aur"].reason == "pkg.reason_no_aur_helper"
    other = {a.key: a for a in restore.package_actions(opened, env("kde", "debian"))}
    assert other["native"].commands == [] and other["native"].reason == "pkg.reason_other_distro"


def test_package_injection_in_archive(src_home, tmp_path, home, monkeypatch):
    from tests.test_archive import rebuild
    path = make_archive(src_home, tmp_path / "out")
    opened = open_archive(path, home)
    (opened.workdir / "packages/native.txt").write_text("firefox\n--config=/tmp/x.conf\n")
    monkeypatch.setattr(restore, "split_available", lambda pl: (pl, []))
    act = restore.package_actions(opened, env("kde", "arch"))[0]
    assert act.packages.invalid == ["--config=/tmp/x.conf"]
    assert act.commands == [["sudo", "pacman", "-S", "--needed", "--", "firefox"]]


# --- Task 31 -------------------------------------------------------------------------------------

def snapshot(home):
    out = {}
    for root, dirs, files in os.walk(home):
        if ".local/state/dotde" in root:
            continue
        for d in dirs:
            rel = os.path.relpath(os.path.join(root, d), home) + "/"
            if not ".local/state/dotde/".startswith(rel):  # DotDE's own state folder is expected
                out[rel] = None
        for f in files:
            p = os.path.join(root, f)
            out[os.path.relpath(p, home)] = open(p, "rb").read()
    return out


def test_undo_restores_exact_state(src_home, tmp_path, home):
    write(home, ".config/kwinrc", b"[Old]\n")
    write(home, ".config/unrelated", b"keep")
    before = snapshot(home)
    opened = open_archive(make_archive(src_home, tmp_path / "out"), home)
    plan = restore.build_plan(opened, load_profile("kde"), load_common(), everything(opened), home)
    restore.restore_immediate(opened, plan, home, "kde")
    assert snapshot(home) != before
    failed = restore.undo_backup(restore.latest_backup(home), home)
    assert not failed and snapshot(home) == before
    assert restore.latest_backup(home) is None  # marked undone


def test_undo_after_interrupted_import(src_home, tmp_path, home, monkeypatch):
    write(home, ".config/kwinrc", b"[Old]\n")
    before = snapshot(home)
    opened = open_archive(make_archive(src_home, tmp_path / "out"), home)
    plan = restore.build_plan(opened, load_profile("kde"), load_common(), everything(opened), home)
    real, calls = restore.atomic_write, {"n": 0}

    def flaky(path, data, mode=None):
        if path.name != "backup.json":
            calls["n"] += 1
            if calls["n"] == 3:
                raise KeyboardInterrupt
        return real(path, data, mode)

    monkeypatch.setattr(restore, "atomic_write", flaky)
    with pytest.raises(KeyboardInterrupt):
        restore.restore_immediate(opened, plan, home, "kde")
    monkeypatch.setattr(restore, "atomic_write", real)
    restore.undo_backup(restore.latest_backup(home), home)
    assert snapshot(home) == before


def test_missing_packages_are_reported_not_installed(src_home, tmp_path, home, monkeypatch):
    from dotde.packages import Package, PackageList
    pkgs = {"native": PackageList("pacman", [Package("firefox"), Package("gone-pkg")])}
    opened = open_archive(make_archive(src_home, tmp_path / "out", packages=pkgs), home)
    monkeypatch.setattr(restore, "split_available",
                        lambda pl: (PackageList(pl.source, [p for p in pl.packages if p.name != "gone-pkg"]), ["gone-pkg"]))
    act = restore.package_actions(opened, env("kde", "arch"))[0]
    assert act.missing == ["gone-pkg"]
    assert act.commands == [["sudo", "pacman", "-S", "--needed", "--", "firefox"]]


def test_dconf_unreachable_files_still_restored(tmp_path, home, monkeypatch):
    src = tmp_path / "old" / "olduser"
    write(src, ".local/share/gnome-shell/extensions/x@y/metadata.json", b"{}")
    calls = []
    monkeypatch.setattr(restore.dconf, "can_load", lambda: False)
    monkeypatch.setattr(restore.dconf, "dump", lambda p: calls.append(p) or "")
    monkeypatch.setattr(restore.dconf, "load", lambda p, d: calls.append(p))
    dump = ("shell", "/org/gnome/shell/", "[/]\nfavorite-apps=['a']\n")
    opened = open_archive(make_archive(src, tmp_path / "out", de="gnome", categories=("shell",), extras=(),
                                       dumps=[dump]), home)
    plan = restore.build_plan(opened, load_profile("gnome"), load_common(), everything(opened), home)
    backup, failed = restore.restore_immediate(opened, plan, home, "gnome")
    assert (home / ".local/share/gnome-shell/extensions/x@y/metadata.json").is_file()
    assert calls == [] and failed == [] and backup.data["status"] == "complete"


def test_dconf_dump_error_does_not_abort(tmp_path, home, monkeypatch):
    src = tmp_path / "old" / "olduser"
    write(src, ".local/share/gnome-shell/extensions/x@y/metadata.json", b"{}")
    loads = []
    monkeypatch.setattr(restore.dconf, "can_load", lambda: True)
    monkeypatch.setattr(restore.dconf, "dump", lambda p: (_ for _ in ()).throw(restore.dconf.DconfError("no bus")))
    monkeypatch.setattr(restore.dconf, "load", lambda p, d: loads.append(p))
    dump = ("shell", "/org/gnome/shell/", "[/]\na=1\n")
    opened = open_archive(make_archive(src, tmp_path / "out", de="gnome", categories=("shell",), extras=(),
                                       dumps=[dump]), home)
    plan = restore.build_plan(opened, load_profile("gnome"), load_common(), everything(opened), home)
    backup, failed = restore.restore_immediate(opened, plan, home, "gnome")
    assert (home / ".local/share/gnome-shell/extensions/x@y/metadata.json").is_file()
    assert loads == [] and failed == [("/org/gnome/shell/", "backup failed")]


def _symlinked_home(tmp_path, home):
    src = tmp_path / "old" / "olduser"
    write(src, ".config/kwinrc", b"[New]\n")
    write(home, ".config/dotfiles/kwinrc", b"[Mine]\n")
    os.symlink("dotfiles/kwinrc", home / ".config/kwinrc")
    opened = open_archive(make_archive(src, tmp_path / "out", categories=("windows",), extras=()), home)
    return opened, restore.build_plan(opened, load_profile("kde"), load_common(), {"windows"}, home)


def test_undo_recreates_symlink(tmp_path, home):
    opened, plan = _symlinked_home(tmp_path, home)
    backup, _ = restore.restore_immediate(opened, plan, home, "kde")
    assert not (home / ".config/kwinrc").is_symlink()
    assert backup.data["symlinks"] == [{"rel": ".config/kwinrc", "target": "dotfiles/kwinrc"}]
    assert backup.data["created_files"] == []
    assert not restore.undo_backup(restore.latest_backup(home), home)
    assert os.readlink(home / ".config/kwinrc") == "dotfiles/kwinrc"
    assert (home / ".config/dotfiles/kwinrc").read_bytes() == b"[Mine]\n"


def test_deferred_undo_recreates_symlink_and_is_not_offered_again(tmp_path, home):
    from dotde import pending
    opened, plan = _symlinked_home(tmp_path, home)
    pending.stage(opened, plan, home, "kde")
    pending.apply_pending(home)  # login: import applied
    pending.stage_undo(restore.latest_backup(home), home)
    pending.apply_pending(home)  # login: undo applied
    assert os.readlink(home / ".config/kwinrc") == "dotfiles/kwinrc"
    assert restore.latest_backup(home) is None  # the undo's own backup is not an "import to undo"


def test_partial_undo_can_be_retried(src_home, tmp_path, home, monkeypatch):
    write(home, ".config/kwinrc", b"[Old]\n")
    opened = open_archive(make_archive(src_home, tmp_path / "out"), home)
    plan = restore.build_plan(opened, load_profile("kde"), load_common(), everything(opened), home)
    restore.restore_immediate(opened, plan, home, "kde")
    backup = restore.latest_backup(home)
    (backup.dir / "files/.config/kwinrc").unlink()  # the saved copy cannot be read
    failed = restore.undo_backup(backup, home)
    assert failed and backup.data["status"] == "partial"
    assert restore.latest_backup(home).dir == backup.dir  # still offered


def test_de_differs_detected_from_tty(src_home, tmp_path, home, monkeypatch):
    opened = open_archive(make_archive(src_home, tmp_path / "out"), home)
    kde = load_profile("kde")
    tty = env("unknown", "arch")
    monkeypatch.setattr(restore, "running_de", lambda: "gnome")
    keys = {n.key for n in restore.compatibility(opened.manifest, tty, kde, home, "6.8.2")}
    assert "warn.de_differs" in keys
    monkeypatch.setattr(restore, "running_de", lambda: "")
    monkeypatch.setattr(restore.shutil, "which", lambda c: None)
    keys = {n.key for n in restore.compatibility(opened.manifest, tty, kde, home, "6.8.2")}
    assert "warn.de_not_installed" in keys and "warn.de_differs" not in keys
    monkeypatch.setattr(restore.shutil, "which", lambda c: "/usr/bin/" + c)
    keys = {n.key for n in restore.compatibility(opened.manifest, tty, kde, home, "6.8.2")}
    assert not keys & {"warn.de_not_installed", "warn.de_differs"}


def test_file_folder_conflicts_are_ignored(src_home, tmp_path, home):
    (home / ".config/kwinrc").mkdir(parents=True)  # a folder where the archive has a file
    write(home, ".local/share/kwin", b"a file where the archive has a folder")
    opened = open_archive(make_archive(src_home, tmp_path / "out"), home)
    plan = restore.build_plan(opened, load_profile("kde"), load_common(), everything(opened), home)
    ignored = dict(plan.ignored)
    assert ignored[".config/kwinrc"] == "conflict"
    assert ignored[".local/share/kwin/scripts/s/blob.bin"] == "conflict"
    restore.restore_immediate(opened, plan, home, "kde")  # the rest is restored without errors
    assert (home / ".config/kglobalshortcutsrc").is_file()
