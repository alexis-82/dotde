"""Deferred restore (KDE with a running session).

Plasma saves its in-memory state at logout, over any file restored during the session. So the
import only *prepares* the files in ~/.local/state/dotde/pending/ and installs a one-shot script
in ~/.config/plasma-workspace/env/. startplasma sources that script at the next login, before
Plasma starts; the script runs `dotde --apply-pending`, which applies the files (with a backup)
and removes the script.
"""

import json
import os
import shlex
import shutil
import sys
import traceback
from datetime import datetime
from pathlib import Path

import dotde
from dotde.archive import OpenedArchive
from dotde.paths import PathError, atomic_write, check_rel, remove_empty_parents, resolve_inside
from dotde.restore import (
    Backup,
    PlanItem,
    RestorePlan,
    apply_items,
    begin_backup,
    finish_backup,
    prepare_content,
    restore_symlink,
)

SCRIPT_NAME = "dotde-pending.sh"


def pending_dir(home: Path) -> Path:
    return home / ".local/state/dotde/pending"


def script_path(home: Path) -> Path:
    return home / ".config/plasma-workspace/env" / SCRIPT_NAME


def log_path(home: Path) -> Path:
    return home / ".local/state/dotde/apply.log"


def last_apply_path(home: Path) -> Path:
    return home / ".local/state/dotde/last-apply.json"


def has_pending(home: Path) -> bool:
    return (pending_dir(home) / "pending.json").is_file()


def pending_info(home: Path) -> dict | None:
    try:
        return json.loads((pending_dir(home) / "pending.json").read_text("utf-8"))
    except (OSError, ValueError):
        return None


def render_script(home: Path) -> str:
    """The script sourced by startplasma. Fixed content: nothing from the archive goes in it.

    It is sourced in the *same* shell as the user's other env scripts, so it must never call
    `exit` or `exec`, must not leave variables behind, and must not write to stdout.
    """
    package_parent = Path(dotde.__file__).resolve().parent.parent
    q = shlex.quote
    return (
        "# DotDE: one-shot restore prepared by `dotde` (deferred import). Removes itself.\n"
        f"mkdir -p {q(str(log_path(home).parent))} 2>/dev/null\n"
        f"PYTHONPATH={q(str(package_parent))} {q(sys.executable)} -m dotde --apply-pending"
        f" >>{q(str(log_path(home)))} 2>&1 || true\n"
        f"rm -f {q(str(script_path(home)))}\n"
    )


def stage(opened: OpenedArchive, plan: RestorePlan, home: Path, de: str) -> None:
    """Move the (already rewritten) files into pending/ and install the login script.

    The caller must have cancelled any previous pending restore.
    """
    pdir = pending_dir(home)
    if pdir.exists():
        raise FileExistsError(str(pdir))
    tmp = pdir.with_name("pending.part")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        for item in plan.items:
            src = opened.workdir / item.member
            dest = tmp / item.member
            dest.parent.mkdir(parents=True, exist_ok=True)
            raw = src.read_bytes()
            data = prepare_content(raw, plan.rewrite)
            if data == raw:
                os.replace(src, dest)  # same filesystem: a move, not a copy
            else:
                atomic_write(dest, data)
        info = {
            "created": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": str(opened.path),
            "de": de,
            "items": [{"rel": i.rel, "member": i.member, "category": i.category, "mode": i.mode} for i in plan.items],
        }
        atomic_write(tmp / "pending.json", json.dumps(info, indent=2).encode())
        os.replace(tmp, pdir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    atomic_write(script_path(home), render_script(home).encode(), 0o644)


def stage_undo(backup: Backup, home: Path) -> None:
    """Undo of a KDE import while Plasma runs: prepare the backup as a pending restore."""
    pdir = pending_dir(home)
    if pdir.exists():
        raise FileExistsError(str(pdir))
    tmp = pdir.with_name("pending.part")
    shutil.rmtree(tmp, ignore_errors=True)
    try:
        items = []
        for rel in backup.data.get("overwritten", []):
            check_rel(rel)
            src = backup.dir / "files" / rel
            dest = tmp / "files" / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            items.append({"rel": rel, "member": f"files/{rel}", "category": "undo", "mode": src.stat().st_mode & 0o777})
        delete = list(backup.data.get("created_files", []))
        for rel in delete:
            check_rel(rel)
        symlinks = list(backup.data.get("symlinks", []))
        for link in symlinks:
            check_rel(link["rel"])
        info = {
            "created": datetime.now().astimezone().isoformat(timespec="seconds"),
            "source": str(backup.dir),
            "de": backup.data.get("de", ""),
            "items": items,
            "delete": delete,
            "symlinks": symlinks,
            "undo_of": str(backup.dir),
        }
        atomic_write(tmp / "pending.json", json.dumps(info, indent=2).encode())
        os.replace(tmp, pdir)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    atomic_write(script_path(home), render_script(home).encode(), 0o644)


def cancel_pending(home: Path) -> None:
    script_path(home).unlink(missing_ok=True)
    shutil.rmtree(pending_dir(home), ignore_errors=True)


def _write_result(home: Path, status: str, message: str = "", backup: str = "") -> None:
    result = {
        "status": status,
        "message": message,
        "backup": backup,
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "seen": False,
    }
    atomic_write(last_apply_path(home), json.dumps(result, indent=2).encode())


def apply_pending(home: Path) -> int:
    """Non-interactive: called by the login script. Always removes the script and pending/."""
    info = pending_info(home)
    if info is None:
        script_path(home).unlink(missing_ok=True)
        return 0
    try:
        items = []
        for raw in info["items"]:
            check_rel(raw["rel"])  # pending.json is re-validated, it is a file on disk
            if raw["member"] != f"files/{raw['rel']}":
                raise PathError(f"unexpected member for {raw['rel']}")
            items.append(PlanItem(raw["rel"], raw["member"], raw["category"], int(raw["mode"]) & 0o777))
        delete = list(info.get("delete", []))
        symlinks = list(info.get("symlinks", []))
        for rel in delete + [link["rel"] for link in symlinks]:
            check_rel(rel)
        kind = "undo" if info.get("undo_of") else "import"
        rels = [i.rel for i in items] + delete + [link["rel"] for link in symlinks]
        backup = begin_backup(home, rels, [], info.get("source", ""), info.get("de", ""), kind)
        apply_items(home, pending_dir(home), items, None)
        for rel in delete:
            resolve_inside(home, rel).unlink(missing_ok=True)
            remove_empty_parents(home, rel)
        for link in symlinks:
            restore_symlink(home, link["rel"], link["target"])
        finish_backup(backup, home)
        if info.get("undo_of"):
            _mark_undone(Path(info["undo_of"]))
        _write_result(home, "ok", backup=str(backup.dir))
        print(f"[{datetime.now():%F %T}] dotde: restored {len(items)} files, backup in {backup.dir}")
        return 0
    except Exception as exc:  # noqa: BLE001 - must never break the login
        _write_result(home, "error", f"{type(exc).__name__}: {exc}")
        print(f"[{datetime.now():%F %T}] dotde: deferred restore failed")
        traceback.print_exc(file=sys.stdout)
        return 1
    finally:
        cancel_pending(home)


def _mark_undone(bdir: Path) -> None:
    try:
        data = json.loads((bdir / "backup.json").read_text("utf-8"))
        data["status"] = "undone"
        atomic_write(bdir / "backup.json", json.dumps(data, indent=2).encode())
    except (OSError, ValueError):
        pass


def last_apply(home: Path) -> dict | None:
    try:
        return json.loads(last_apply_path(home).read_text("utf-8"))
    except (OSError, ValueError):
        return None


def mark_last_apply_seen(home: Path) -> None:
    data = last_apply(home)
    if data is not None and not data.get("seen"):
        data["seen"] = True
        atomic_write(last_apply_path(home), json.dumps(data, indent=2).encode())
