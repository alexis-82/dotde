"""Desktop environment profiles: which files and dconf paths belong to which category.

Profiles are TOML files in dotde/profiles/. `common.toml` holds categories shared by every
desktop plus the global exclusions; the other files describe one desktop each.
"""

import os
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from importlib import resources

from dotde.paths import PathError, check_pattern, is_under, to_rel

RESTORE_MODES = ("immediate", "deferred", "offline")
COMMON_ID = "common"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_DCONF_RE = re.compile(r"^/([A-Za-z0-9_.-]+/)+$")


class ProfileError(ValueError):
    pass


@dataclass
class Category:
    id: str
    label: dict[str, str]
    paths: list[str] = field(default_factory=list)  # home-relative, dirs end with "/"
    dconf: list[str] = field(default_factory=list)  # dconf directories, e.g. /org/gnome/shell/
    profile: str = ""  # id of the profile the category comes from


@dataclass
class Profile:
    id: str
    name: str
    categories: list[Category]
    exclude: list[str] = field(default_factory=list)
    version_cmd: list[str] = field(default_factory=list)
    running_process: str = ""
    restore_mode: str = "immediate"
    logout_cmd: list[str] = field(default_factory=list)
    secret_patterns: list[str] = field(default_factory=list)  # only in common.toml
    sensitive_apps: list[str] = field(default_factory=list)  # only in common.toml

    @property
    def all_excludes(self) -> list[str]:
        return self.exclude + self.secret_patterns

    def category(self, cat_id: str) -> Category | None:
        return next((c for c in self.categories if c.id == cat_id), None)


def _require(table: dict, key: str, kind: type, where: str):
    if key not in table:
        raise ProfileError(f"{where}: missing field '{key}'")
    value = table[key]
    if not isinstance(value, kind):
        raise ProfileError(f"{where}: field '{key}' must be {kind.__name__}")
    return value


def _str_list(table: dict, key: str, where: str) -> list[str]:
    value = table.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ProfileError(f"{where}: field '{key}' must be a list of strings")
    return value


_TOP_KEYS = {"meta", "category", "exclude", "secret_patterns", "sensitive_apps"}
_META_KEYS = {"id", "name", "version_cmd", "running_process", "restore_mode", "logout_cmd"}
_CATEGORY_KEYS = {"id", "label", "paths", "dconf"}


def _check_keys(table: dict, allowed: set[str], where: str) -> None:
    unknown = set(table) - allowed
    if unknown:
        # A common TOML mistake: top-level keys written after a [[category]] end up inside it.
        raise ProfileError(f"{where}: unknown field(s): {', '.join(sorted(unknown))}")


def parse_profile(data: dict, source: str = "<profile>") -> Profile:
    _check_keys(data, _TOP_KEYS, source)
    meta = _require(data, "meta", dict, source)
    _check_keys(meta, _META_KEYS, f"{source} [meta]")
    pid = _require(meta, "id", str, f"{source} [meta]")
    if not _ID_RE.match(pid):
        raise ProfileError(f"{source}: invalid profile id '{pid}'")
    restore_mode = meta.get("restore_mode", "immediate")
    if restore_mode not in RESTORE_MODES:
        raise ProfileError(f"{source}: restore_mode must be one of {RESTORE_MODES}, not '{restore_mode}'")

    categories: list[Category] = []
    for i, raw in enumerate(data.get("category", [])):
        where = f"{source} category #{i + 1}"
        _check_keys(raw, _CATEGORY_KEYS, where)
        cid = _require(raw, "id", str, where)
        if not _ID_RE.match(cid):
            raise ProfileError(f"{where}: invalid category id '{cid}'")
        lab = _require(raw, "label", dict, where)
        if "en" not in lab:
            raise ProfileError(f"{where}: label needs at least an 'en' entry")
        try:
            paths = [to_rel(p) for p in _str_list(raw, "paths", where)]
        except PathError as exc:
            raise ProfileError(f"{where} ('{cid}'): {exc}") from None
        dconf = _str_list(raw, "dconf", where)
        for d in dconf:
            if not _DCONF_RE.match(d):
                raise ProfileError(f"{where} ('{cid}'): invalid dconf path '{d}' (must start and end with '/')")
        if not paths and not dconf:
            raise ProfileError(f"{where} ('{cid}'): category has no paths and no dconf entries")
        categories.append(Category(cid, dict(lab), paths, dconf, pid))

    ids = [c.id for c in categories]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ProfileError(f"{source}: duplicate category id(s): {', '.join(sorted(dupes))}")

    exclude = _str_list(data, "exclude", source)
    secret_patterns = _str_list(data, "secret_patterns", source)
    for pattern in exclude + secret_patterns:
        try:
            check_pattern(pattern)
        except PathError as exc:
            raise ProfileError(f"{source}: {exc}") from None

    profile = Profile(
        id=pid,
        name=meta.get("name", pid),
        categories=categories,
        exclude=exclude,
        version_cmd=_str_list(meta, "version_cmd", f"{source} [meta]"),
        running_process=meta.get("running_process", ""),
        restore_mode=restore_mode,
        logout_cmd=_str_list(meta, "logout_cmd", f"{source} [meta]"),
        secret_patterns=secret_patterns,
        sensitive_apps=_str_list(data, "sensitive_apps", source),
    )
    check_overlaps(profile.categories)
    return profile


def check_overlaps(categories: list[Category]) -> None:
    """Refuse file or dconf paths of one category that contain (or equal) those of another."""
    owners_f = [(p, c.id) for c in categories for p in c.paths]
    owners_d = [(p, c.id) for c in categories for p in c.dconf]
    for owners in (owners_f, owners_d):
        for i, (a, ca) in enumerate(owners):
            for b, cb in owners[i + 1 :]:
                if ca != cb and (is_under(a, b) or is_under(b, a)):
                    raise ProfileError(f"categories '{ca}' and '{cb}' overlap: '{a}' / '{b}'")


def _read_profile_text(pid: str) -> str:
    try:
        return resources.files("dotde").joinpath("profiles", f"{pid}.toml").read_text("utf-8")
    except FileNotFoundError:
        raise ProfileError(f"unknown profile '{pid}'") from None


def load_profile(pid: str) -> Profile:
    if not _ID_RE.match(pid):
        raise ProfileError(f"unknown profile '{pid}'")
    text = _read_profile_text(pid)
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ProfileError(f"{pid}.toml: {exc}") from None
    profile = parse_profile(data, f"{pid}.toml")
    if profile.id != pid:
        raise ProfileError(f"{pid}.toml: [meta] id is '{profile.id}'")
    return profile


def available_profiles() -> list[str]:
    folder = resources.files("dotde").joinpath("profiles")
    ids = sorted(e.name[:-5] for e in folder.iterdir() if e.name.endswith(".toml"))
    return [i for i in ids if i != COMMON_ID]


def load_common() -> Profile:
    return load_profile(COMMON_ID)


def combined_categories(profile: Profile | None, common: Profile) -> list[Category]:
    """Categories of a desktop profile followed by the common ones, checked for overlaps."""
    cats = (profile.categories if profile else []) + common.categories
    check_overlaps(cats)
    return cats


def de_version(profile: Profile, timeout: float = 5.0) -> str:
    """Version of the running desktop from `version_cmd`, or '' if it cannot be read."""
    if not profile.version_cmd:
        return ""
    if not (os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY")):
        # Some desktop binaries (plasmashell) abort or hang without a display: from a TTY the
        # version stays unknown and the version check is simply skipped.
        return ""
    try:
        out = subprocess.run(
            profile.version_cmd, capture_output=True, text=True, timeout=timeout, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    match = re.search(r"\d+(?:\.\d+)+", out)
    return match.group(0) if match else ""
