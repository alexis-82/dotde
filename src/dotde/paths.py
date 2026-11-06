"""Path rules shared by export and import.

Paths in profiles and archives are handled as *relative paths* from the home directory
(".config/kwinrc"), written in profiles as "~/.config/kwinrc". Directories end with "/".
"""

import os
import re
import tempfile
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath

ROOTS = (".config", ".local", ".themes", ".icons")
BLACKLIST = (
    ".local/bin",
    ".local/state/dotde",
    ".config/plasma-workspace/env",
    ".config/systemd",
)


class PathError(ValueError):
    """A path that DotDE must never read from or write to."""


def home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def current_user() -> str:
    import pwd

    try:
        return os.environ.get("USER") or pwd.getpwuid(os.getuid()).pw_name
    except KeyError:
        return ""


def state_dir() -> Path:
    return home() / ".local" / "state" / "dotde"


def to_rel(profile_path: str) -> str:
    """'~/.config/x/' -> '.config/x/' (trailing slash kept). Raises PathError if not under ~."""
    if not profile_path.startswith("~/"):
        raise PathError(f"path must start with '~/': {profile_path}")
    rel = profile_path[2:]
    check_rel(rel)
    return rel


def check_rel(rel: str) -> None:
    """Validate a home-relative path: inside an allowed root, outside the blacklist, no '..'."""
    if not rel or rel.startswith("/") or "\\" in rel or "\x00" in rel:
        raise PathError(f"invalid path: {rel!r}")
    parts = PurePosixPath(rel).parts
    if any(p in ("..", ".") for p in parts):
        raise PathError(f"path must not contain '.' or '..': {rel}")
    if parts[0] not in ROOTS:
        raise PathError(f"path outside allowed roots {ROOTS}: {rel}")
    if is_blacklisted(rel):
        raise PathError(f"path is in the DotDE blacklist: {rel}")


def is_blacklisted(rel: str) -> bool:
    """True if `rel` is inside a blacklisted directory or contains one (e.g. '~/.local/')."""
    norm = rel.rstrip("/")
    return any(is_under(norm, b) or is_under(b, norm) for b in BLACKLIST)


def is_allowed_rel(rel: str) -> bool:
    try:
        check_rel(rel)
    except PathError:
        return False
    return True


def is_under(rel: str, parent: str) -> bool:
    """True if `rel` equals `parent` or lies inside it. `parent` ending with '/' is a directory."""
    rel_n, parent_n = rel.rstrip("/"), parent.rstrip("/")
    return rel_n == parent_n or rel_n.startswith(parent_n + "/")


def resolve_inside(home_dir: Path, rel: str) -> Path:
    """Absolute path for `rel`, refusing symlinks that escape the root it belongs to."""
    check_rel(rel)
    root = PurePosixPath(rel).parts[0]
    target = (home_dir / rel).resolve(strict=False)
    root_real = (home_dir / root).resolve(strict=False)
    if target != root_real and root_real not in target.parents:
        raise PathError(f"path escapes {root} through a symlink: {rel}")
    return home_dir / rel


def remove_empty_parents(home_dir: Path, rel: str) -> None:
    """After deleting `rel`, remove the folders that became empty, never the root or above."""
    parts = PurePosixPath(rel).parts
    for depth in range(len(parts) - 1, 1, -1):  # stop before the root (.config, .local, ...)
        folder = home_dir.joinpath(*parts[:depth])
        try:
            folder.rmdir()  # only succeeds if empty
        except OSError:
            return


# --- exclusions ------------------------------------------------------------------------------


def check_pattern(pattern: str) -> None:
    if pattern.startswith("~/"):
        return
    if pattern.startswith("**/"):
        rest = pattern[3:].rstrip("/")
        if rest and "/" not in rest:
            return
    raise PathError(f"invalid exclude pattern (use '~/...' or '**/name'): {pattern}")


def matches_exclude(rel: str, pattern: str, is_dir: bool = False) -> bool:
    """Match a home-relative path against an exclude pattern.

    '~/a/b/'   -> anything at or below .../a/b
    '~/a/*.x'  -> glob on the full relative path
    '**/name/' -> any directory component matching `name` (glob)
    '**/name'  -> any component (file or directory) matching `name` (glob)
    """
    rel_n = rel.rstrip("/")
    if pattern.startswith("~/"):
        anchored = pattern[2:]
        if anchored.endswith("/"):
            return is_under(rel_n, anchored)
        return fnmatchcase(rel_n, anchored) or any(
            fnmatchcase(str(p), anchored) for p in PurePosixPath(rel_n).parents
        )
    name = pattern[3:]
    parts = PurePosixPath(rel_n).parts
    if name.endswith("/"):
        dirs = parts if is_dir else parts[:-1]
        return any(fnmatchcase(p, name[:-1]) for p in dirs)
    return any(fnmatchcase(p, name) for p in parts)


def is_excluded(rel: str, patterns: list[str], is_dir: bool = False) -> bool:
    return any(matches_exclude(rel, p, is_dir) for p in patterns)


# --- content helpers ---------------------------------------------------------------------------


def is_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def rewrite_home(data: bytes, old: str, new: str) -> bytes:
    """Replace the old home path with the new one, only at path boundaries.

    '/home/old' and '/home/old/x' are rewritten, '/home/oldie' is not.
    """
    old, new = old.rstrip("/"), new.rstrip("/")
    if not old or old == new:
        return data
    pattern = re.compile(re.escape(old.encode()) + rb"(?![A-Za-z0-9._-])")
    return pattern.sub(new.encode().replace(b"\\", b"\\\\"), data)


def atomic_write(path: Path, data: bytes, mode: int | None = None) -> None:
    """Write via a temporary file in the same directory + os.replace: never a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".dotde-tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if mode is not None:
            os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
