"""Import: from an opened archive to files written in the home, with a backup that allows undo."""

import json
import os
import shutil
import signal
import socket
import subprocess
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from dotde import dconf
from dotde.archive import OpenedArchive
from dotde.collect import EXTRA_PREFIX, valid_extra_name
from dotde.detect import Environment
from dotde.packages import (
    ARCHIVE_FILES,
    NATIVE_BY_FAMILY,
    PackageList,
    aur_helper,
    install_commands,
    local_flatpak_remotes,
    parse_archive,
    split_available,
)
from dotde.paths import (
    PathError,
    atomic_write,
    check_rel,
    current_user,
    is_blacklisted,
    is_excluded,
    is_text,
    is_under,
    remove_empty_parents,
    resolve_inside,
    rewrite_home,
    state_dir,
)
from dotde.profiles import Category, Profile, ProfileError, de_version, load_profile
from dotde.session import running_de

KEEP_BACKUPS = 3
Progress = Callable[[int, int], None]


# --- Task 21: profile from the manifest, compatibility warnings ---------------------------------


@dataclass
class Notice:
    key: str  # i18n key
    params: dict = field(default_factory=dict)


def profile_from_manifest(manifest: dict) -> tuple[Profile | None, list[Notice]]:
    """The profile is the one recorded in the archive, never the desktop detected now."""
    pid = manifest.get("de", {}).get("id", "")
    if not pid or pid == "unknown":
        return None, [Notice("warn.no_profile_in_archive")]
    try:
        return load_profile(pid), []
    except ProfileError:
        return None, [Notice("warn.unknown_profile", {"profile": pid})]


def _major(version: str) -> str:
    return version.split(".")[0] if version else ""


def compatibility(manifest: dict, env: Environment, profile: Profile | None, home: Path,
                  local_version: str | None = None) -> list[Notice]:
    notices = []
    a_de = manifest.get("de", {})
    current = env.de if env.de != "unknown" else running_de()  # from a TTY: look at the processes
    if current and a_de.get("id") != current:
        notices.append(Notice("warn.de_differs", {"archive": a_de.get("name", a_de.get("id")), "current": current}))
    elif not current and profile is not None and profile.version_cmd and not shutil.which(profile.version_cmd[0]):
        notices.append(Notice("warn.de_not_installed", {"archive": profile.name}))
    if profile is not None:
        local = de_version(profile) if local_version is None else local_version
        if local and a_de.get("version") and _major(local) != _major(a_de["version"]):
            notices.append(Notice("warn.de_major", {"archive": a_de["version"], "current": local}))
    a_family = manifest.get("distro", {}).get("family", "unknown")
    if a_family != env.distro.family:
        notices.append(Notice("warn.distro_family", {"archive": a_family, "current": env.distro.family}))
    if manifest.get("home") and manifest["home"].rstrip("/") != str(home).rstrip("/"):
        notices.append(Notice("info.home_rewrite", {"old": manifest["home"], "new": str(home)}))
    user, host = current_user(), socket.gethostname()
    if manifest.get("user") != user or manifest.get("hostname") != host:
        notices.append(Notice("warn.other_origin", {"user": manifest.get("user", "?"), "host": manifest.get("hostname", "?")}))
    return notices


# --- Task 22: restore plan ------------------------------------------------------------------------


@dataclass
class PlanItem:
    rel: str
    member: str  # path inside the extracted archive
    category: str
    mode: int


@dataclass
class RestorePlan:
    items: list[PlanItem] = field(default_factory=list)
    ignored: list[tuple[str, str]] = field(default_factory=list)  # (rel, reason)
    autostart: list[str] = field(default_factory=list)
    extras: list[str] = field(default_factory=list)
    dconf: list[tuple[str, str, str]] = field(default_factory=list)  # (category, dconf path, member)
    old_home: str = ""
    new_home: str = ""

    @property
    def rewrite(self) -> tuple[str, str] | None:
        if self.old_home and self.old_home.rstrip("/") != self.new_home.rstrip("/"):
            return self.old_home, self.new_home
        return None


def archive_categories(manifest: dict, profile: Profile | None, common: Profile) -> list[Category]:
    """Categories of the archive that this DotDE knows how to restore (local definitions)."""
    known = {c.id: c for c in (profile.categories if profile else []) + common.categories}
    out = []
    for entry in manifest["categories"]:
        cid = entry["id"]
        if cid in known:
            out.append(known[cid])
        elif cid.startswith(EXTRA_PREFIX):
            name = cid[len(EXTRA_PREFIX) :]
            out.append(Category(cid, {"en": name}, [f".config/{name}/"], profile="extra"))
    return out


def build_plan(opened: OpenedArchive, profile: Profile | None, common: Profile, selected: set[str],
               home: Path) -> RestorePlan:
    manifest = opened.manifest
    plan = RestorePlan(old_home=manifest.get("home", ""), new_home=str(home))
    local_cats = {c.id: c for c in (profile.categories if profile else []) + common.categories}
    covered = [p for c in local_cats.values() for p in c.paths]
    excludes = common.all_excludes + (profile.exclude if profile else [])

    for f in manifest["files"]:
        rel, cat_id = f["path"], f["category"]
        if cat_id not in selected:
            continue
        reason = _refuse(rel, cat_id, local_cats, covered, excludes)
        if reason:
            plan.ignored.append((rel, reason))
            continue
        try:
            resolve_inside(home, rel)
        except PathError:
            plan.ignored.append((rel, "symlink"))
            continue
        if _type_conflict(home, rel):
            plan.ignored.append((rel, "conflict"))
            continue
        plan.items.append(PlanItem(rel, f"files/{rel}", cat_id, int(f.get("mode", 0o644)) & 0o777))
        if is_under(rel, ".config/autostart/") and rel.endswith(".desktop"):
            plan.autostart.append(rel)

    plan.extras = sorted(
        c["id"][len(EXTRA_PREFIX) :] for c in manifest["categories"]
        if c["id"].startswith(EXTRA_PREFIX) and c["id"] in selected
    )
    for d in manifest["dconf"]:
        cat = local_cats.get(d["category"])
        if d["category"] in selected and cat and d["path"] in cat.dconf:
            plan.dconf.append((d["category"], d["path"], d["file"]))
        elif d["category"] in selected:
            plan.ignored.append((d["path"], "outside_category"))
    return plan


def _type_conflict(home: Path, rel: str) -> bool:
    """A file of the archive where a folder exists here, or below something that is a file here."""
    target = home / rel
    if target.is_dir() and not target.is_symlink():
        return True
    parent = target.parent
    while parent != home:
        if parent.exists() and not parent.is_dir():
            return True
        parent = parent.parent
    return False


def _refuse(rel: str, cat_id: str, local_cats: dict[str, Category], covered: list[str], excludes: list[str]) -> str:
    """Reason why a file of the archive must not be written, or '' if it is acceptable."""
    try:
        check_rel(rel)
    except PathError:
        return "forbidden_path"
    if is_blacklisted(rel):
        return "forbidden_path"
    if is_excluded(rel, excludes):
        return "excluded"
    if cat_id.startswith(EXTRA_PREFIX):
        name = cat_id[len(EXTRA_PREFIX) :]
        folder = f".config/{name}/"
        if not valid_extra_name(name) or not is_under(rel, folder):
            return "outside_category"
        if any(is_under(p, folder) or is_under(folder, p) for p in covered):
            return "outside_category"  # an "extra" must not overlap a profile category
        return ""
    cat = local_cats.get(cat_id)
    if cat is None:
        return "unknown_category"
    if not any(is_under(rel, p) for p in cat.paths):
        return "outside_category"
    return ""


# --- Task 23: backup journal ------------------------------------------------------------------------


def backups_root(home: Path | None = None) -> Path:
    return (home / ".local/state/dotde") if home else state_dir()


@dataclass
class Backup:
    dir: Path
    data: dict

    def save(self) -> None:
        atomic_write(self.dir / "backup.json", json.dumps(self.data, indent=2).encode())


def _new_backup_dir(root: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = root / f"backup-{stamp}"
    n = 1
    while path.exists():
        n += 1
        path = root / f"backup-{stamp}-{n}"
    path.mkdir(parents=True)
    return path


def begin_backup(home: Path, rels: list[str], dconf_paths: list[str], source: str, de: str,
                 kind: str = "import") -> Backup:
    """Write the journal *before* touching anything, then copy the files that will be replaced.

    `kind` is "import", or "undo" when the backup protects the application of an undo: those are
    never offered by "Undo last import" (undoing them would redo the import).
    """
    bdir = _new_backup_dir(backups_root(home))
    symlinks = [{"rel": r, "target": os.readlink(home / r)} for r in rels if (home / r).is_symlink()]
    linked = {s["rel"] for s in symlinks}
    existing = [r for r in rels if r not in linked and (home / r).is_file()]
    created = [r for r in rels if r not in linked and r not in set(existing)]
    backup = Backup(bdir, {
        "status": "in_progress",
        "kind": kind,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": source,
        "de": de,
        "overwritten": existing,
        "symlinks": symlinks,  # replaced by a regular file: recreated as links on undo
        "created_files": created,
        "dconf": [],
    })
    backup.save()
    for rel in existing:
        dest = bdir / "files" / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(home / rel, dest)
    for i, path in enumerate(dconf_paths, 1):
        try:
            dump = dconf.dump(path)
        except dconf.DconfError:
            continue  # not backed up -> not loaded either (see restore_immediate)
        name = f"dconf/{i}.ini"
        atomic_write(bdir / name, dump.encode())
        backup.data["dconf"].append({"path": path, "file": name})
    backup.save()
    return backup


def finish_backup(backup: Backup, home: Path) -> None:
    backup.data["status"] = "complete"
    backup.save()
    prune_backups(home)


def list_backups(home: Path) -> list[Path]:
    root = backups_root(home)
    if not root.is_dir():
        return []
    return sorted((p for p in root.iterdir() if p.is_dir() and p.name.startswith("backup-")), key=lambda p: p.name)


def prune_backups(home: Path, keep: int = KEEP_BACKUPS) -> None:
    backups = list_backups(home)
    for old in backups[:-keep] if len(backups) > keep else []:
        shutil.rmtree(old, ignore_errors=True)


# --- Task 24: applying files ---------------------------------------------------------------------


@contextmanager
def deferred_sigint():
    """Postpone Ctrl+C until the current file is fully written; then stop cleanly."""
    if threading.current_thread() is not threading.main_thread():
        yield lambda: False
        return
    hit = {"flag": False}

    def handler(signum, frame):
        hit["flag"] = True

    previous = signal.signal(signal.SIGINT, handler)
    try:
        yield lambda: hit["flag"]
    finally:
        signal.signal(signal.SIGINT, previous)


def prepare_content(data: bytes, rewrite: tuple[str, str] | None) -> bytes:
    if rewrite and is_text(data):
        return rewrite_home(data, *rewrite)
    return data


def apply_items(home: Path, source_dir: Path, items: list[PlanItem], rewrite: tuple[str, str] | None,
                progress: Progress | None = None) -> None:
    with deferred_sigint() as interrupted:
        for i, item in enumerate(items, 1):
            data = prepare_content((source_dir / item.member).read_bytes(), rewrite)
            atomic_write(resolve_inside(home, item.rel), data, item.mode or 0o644)
            if progress:
                progress(i, len(items))
            if interrupted():
                raise KeyboardInterrupt


# --- Task 25: dconf ------------------------------------------------------------------------------


def apply_dconf(opened: OpenedArchive, plan: RestorePlan, only: set[str]) -> list[tuple[str, str]]:
    """Load the dconf dumps whose path is in `only`; returns (path, error) for the failures."""
    failed = []
    for _cat, path, member in plan.dconf:
        if path not in only:
            continue
        text = prepare_content(opened.file_bytes(member), plan.rewrite).decode("utf-8")
        try:
            dconf.load(path, text)
        except dconf.DconfError as exc:
            failed.append((path, str(exc)))
    return failed


def restore_immediate(opened: OpenedArchive, plan: RestorePlan, home: Path, de: str,
                      progress: Progress | None = None) -> tuple[Backup, list[tuple[str, str]]]:
    # dconf unreachable (e.g. TTY without session bus): files are restored anyway, dconf skipped,
    # as the summary told the user. A section is loaded only if its current state was backed up.
    dconf_paths = [p for _c, p, _m in plan.dconf] if plan.dconf and dconf.can_load() else []
    backup = begin_backup(home, [i.rel for i in plan.items], dconf_paths, str(opened.path), de)
    apply_items(home, opened.workdir, plan.items, plan.rewrite, progress)
    backed_up = {d["path"] for d in backup.data["dconf"]}
    failed = apply_dconf(opened, plan, backed_up) if backed_up else []
    failed += [(p, "backup failed") for p in dconf_paths if p not in backed_up]
    finish_backup(backup, home)
    return backup, failed


# --- Task 26: packages ---------------------------------------------------------------------------


@dataclass
class PackageAction:
    key: str  # native / aur / flatpak / snap
    packages: PackageList
    commands: list[list[str]]
    reason: str = ""  # i18n key explaining why there are no commands
    missing: list[str] = field(default_factory=list)  # not available in the repositories any more


def package_actions(opened: OpenedArchive, env: Environment) -> list[PackageAction]:
    actions = []
    same_family = opened.manifest.get("distro", {}).get("family") == env.distro.family != "unknown"
    for key, entry in opened.manifest["packages"].items():
        remotes = opened.text(entry["remotes_file"]) if entry.get("remotes_file") else ""
        pl = parse_archive(entry["source"], opened.text(entry["file"]), remotes)
        if not pl.packages:
            continue
        reason = ""
        if key in ("native", "aur") and not same_family:
            reason = "pkg.reason_other_distro"
        elif key == "native" and entry["source"] != NATIVE_BY_FAMILY.get(env.distro.family):
            reason = "pkg.reason_other_distro"
        elif key == "aur" and not aur_helper():
            reason = "pkg.reason_no_aur_helper"
        elif key in ("flatpak", "snap") and not shutil.which(key):
            reason = "pkg.reason_missing_tool"
        missing: list[str] = []
        if not reason and key == "native":
            pl_ok, missing = split_available(pl)
        else:
            pl_ok = pl
        cmds = [] if reason else install_commands(pl_ok, local_flatpak_remotes() if key == "flatpak" else None)
        actions.append(PackageAction(key, pl, cmds, reason, missing))
    return actions


def run_commands(commands: list[list[str]]) -> list[list[str]]:
    """Run interactively (sudo may ask for a password). Returns the commands that failed."""
    failed = []
    for cmd in commands:
        try:
            if subprocess.run(cmd, check=False).returncode != 0:
                failed.append(cmd)
        except OSError:
            failed.append(cmd)
    return failed


# --- Task 31: undo ----------------------------------------------------------------------------------


def latest_backup(home: Path) -> Backup | None:
    for bdir in reversed(list_backups(home)):
        try:
            data = json.loads((bdir / "backup.json").read_text("utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("kind", "import") == "undo":
            continue
        if data.get("status") in ("complete", "in_progress", "partial"):
            return Backup(bdir, data)
    return None


def undo_backup(backup: Backup, home: Path) -> list[str]:
    """Put back the replaced files, delete the created ones, reload dconf. Returns failures."""
    failed = []
    with deferred_sigint():
        for rel in backup.data.get("overwritten", []):
            try:
                check_rel(rel)
                src = backup.dir / "files" / rel
                atomic_write(resolve_inside(home, rel), src.read_bytes(), src.stat().st_mode & 0o777)
            except (OSError, PathError) as exc:
                failed.append(f"{rel}: {exc}")
        for link in backup.data.get("symlinks", []):
            try:
                restore_symlink(home, link["rel"], link["target"])
            except (OSError, PathError, KeyError) as exc:
                failed.append(f"{link.get('rel', '?')}: {exc}")
        for rel in backup.data.get("created_files", []):
            try:
                check_rel(rel)
                resolve_inside(home, rel).unlink(missing_ok=True)
                remove_empty_parents(home, rel)
            except (OSError, PathError) as exc:
                failed.append(f"{rel}: {exc}")
        for d in backup.data.get("dconf", []):
            try:
                dconf.reset(d["path"])
                dconf.load(d["path"], (backup.dir / d["file"]).read_text("utf-8"))
            except (OSError, dconf.DconfError) as exc:
                failed.append(f"{d['path']}: {exc}")
    # "partial": something could not be put back, the undo can be tried again from the menu
    backup.data["status"] = "partial" if failed else "undone"
    backup.save()
    return failed


def restore_symlink(home: Path, rel: str, target: str) -> None:
    """Put back a symbolic link that an import had replaced with a regular file."""
    check_rel(rel)
    path = home / rel
    resolve_inside(home, str(Path(rel).parent) + "/x")  # the folder holding the link stays inside its root
    if path.is_symlink() or path.exists():
        path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(target, path)
