"""From selected categories and extra app folders to the concrete list of files to export."""

import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from dotde.paths import PathError, is_blacklisted, is_excluded, is_under, resolve_inside
from dotde.profiles import Category

EXTRA_PREFIX = "extra:"
_EXTRA_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def valid_extra_name(name: str) -> bool:
    """An "extra app" is one folder directly under ~/.config (no '/', no '.'/'..')."""
    return (
        len(name) <= 255
        and bool(_EXTRA_NAME_RE.match(name))
        and name not in (".", "..")
        and not is_blacklisted(f".config/{name}")
    )


@dataclass
class CollectedFile:
    rel: str  # home-relative path
    category: str  # category id, or "extra:<folder>"
    size: int
    mode: int


@dataclass
class Collection:
    files: list[CollectedFile] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (rel, reason)
    secrets_found: int = 0  # files left out because they match a secret pattern

    @property
    def total_size(self) -> int:
        return sum(f.size for f in self.files)


@dataclass
class ExtraCandidate:
    name: str  # folder name under ~/.config
    size: int
    sensitive: bool


def extra_category(name: str) -> Category:
    return Category(id=EXTRA_PREFIX + name, label={"en": name}, paths=[f".config/{name}/"], profile="extra")


def _walk(
    home: Path, rel: str, excludes: list[str], secrets: list[str], out: Collection, category: str, seen: set[str]
) -> None:
    top = home / rel
    try:
        st = os.lstat(top)
    except FileNotFoundError:
        return  # every profile path is optional
    except OSError as exc:
        out.skipped.append((rel, exc.strerror or str(exc)))
        return
    if not stat.S_ISLNK(st.st_mode):
        try:
            resolve_inside(home, rel)  # a symlinked parent folder must not lead outside its root
        except PathError as exc:
            out.skipped.append((rel, str(exc)))
            return

    def add_file(file_rel: str, st: os.stat_result) -> None:
        if file_rel in seen or is_blacklisted(file_rel) or is_excluded(file_rel, excludes):
            return
        if is_excluded(file_rel, secrets):
            out.secrets_found += 1
            return
        if not os.access(home / file_rel, os.R_OK):
            out.skipped.append((file_rel, "permission denied"))
            return
        seen.add(file_rel)
        out.files.append(CollectedFile(file_rel, category, st.st_size, stat.S_IMODE(st.st_mode)))

    if stat.S_ISLNK(st.st_mode):
        out.skipped.append((rel.rstrip("/"), "symbolic link"))
        return
    if stat.S_ISREG(st.st_mode):
        add_file(rel.rstrip("/"), st)
        return
    if not stat.S_ISDIR(st.st_mode):
        return

    base = rel.rstrip("/")
    for dirpath, dirnames, filenames in os.walk(top, onerror=lambda e: out.skipped.append((base, str(e)))):
        dir_rel = base + dirpath[len(str(top)) :]
        keep = []
        for d in sorted(dirnames):
            d_rel = f"{dir_rel}/{d}"
            if os.path.islink(os.path.join(dirpath, d)):
                out.skipped.append((d_rel, "symbolic link"))
            elif not is_blacklisted(d_rel) and not is_excluded(d_rel, excludes, is_dir=True):
                keep.append(d)
        dirnames[:] = keep
        for name in sorted(filenames):
            f_rel = f"{dir_rel}/{name}"
            try:
                fst = os.lstat(os.path.join(dirpath, name))
            except OSError as exc:
                out.skipped.append((f_rel, exc.strerror or str(exc)))
                continue
            if stat.S_ISLNK(fst.st_mode):
                out.skipped.append((f_rel, "symbolic link"))
            elif stat.S_ISREG(fst.st_mode):
                add_file(f_rel, fst)


def collect(
    home: Path, categories: list[Category], excludes: list[str], secret_patterns: list[str] = ()
) -> Collection:
    """Files of the given categories. Paths matching `excludes` or `secret_patterns` are left out."""
    out = Collection()
    seen: set[str] = set()
    for cat in categories:
        for rel in cat.paths:
            _walk(home, rel, excludes, list(secret_patterns), out, cat.id, seen)
    return out


def extra_candidates(
    home: Path,
    covered: list[Category],
    excludes: list[str],
    secret_patterns: list[str],
    sensitive_apps: list[str],
) -> list[ExtraCandidate]:
    """Folders of ~/.config not covered by any profile category, offered as "extra apps"."""
    config = home / ".config"
    covered_paths = [p for c in covered for p in c.paths]
    result = []
    try:
        entries = sorted(os.scandir(config), key=lambda e: e.name.lower())
    except OSError:
        return []
    for entry in entries:
        rel = f".config/{entry.name}"
        if not entry.is_dir(follow_symlinks=False) or entry.name.startswith("."):
            continue
        if is_blacklisted(rel) or is_excluded(rel, excludes, is_dir=True):
            continue
        if any(is_under(p, rel) or is_under(rel, p) for p in covered_paths):
            continue
        kept = collect(home, [extra_category(entry.name)], excludes, secret_patterns)
        sensitive = entry.name in sensitive_apps or kept.secrets_found > 0
        result.append(ExtraCandidate(entry.name, kept.total_size, sensitive))
    return result
