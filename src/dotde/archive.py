"""The DotDE archive: writing it on export, reading and validating it on import.

Layout:
    manifest.json
    files/<home-relative path>
    dconf/<category>/<n>.ini
    packages/{native,aur,flatpak,snap}.txt, packages/flatpak-remotes.txt
"""

import hashlib
import io
import json
import os
import re
import shutil
import socket
import tarfile
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from dotde import __version__
from dotde.collect import EXTRA_PREFIX, Collection, valid_extra_name
from dotde.packages import ARCHIVE_FILES, FLATPAK_REMOTES_FILE, PackageList, serialize, serialize_remotes
from dotde.paths import PathError, check_rel, current_user

FORMAT = 1
MANIFEST = "manifest.json"
MAX_MANIFEST = 32 * 1024 * 1024
_DCONF_RE = re.compile(r"^/([A-Za-z0-9_.-]+/)+$")

Progress = Callable[[int, int], None]  # (done, total)


class ArchiveError(ValueError):
    pass


@dataclass
class DconfDump:
    category: str
    path: str  # dconf directory, e.g. /org/gnome/shell/
    data: str


@dataclass
class ExportMeta:
    distro: dict
    de: dict  # {"id", "name", "version"}
    categories: list[dict]  # [{"id", "profile", "label"}] — selected categories, extras included
    user: str = field(default_factory=current_user)
    hostname: str = field(default_factory=socket.gethostname)
    home: str = ""


def archive_name(de: str, hostname: str, now: datetime | None = None) -> str:
    now = now or datetime.now()
    safe = lambda s: re.sub(r"[^A-Za-z0-9_-]+", "-", s).strip("-") or "x"  # noqa: E731
    return f"dotde-{safe(de)}-{safe(hostname)}-{now:%Y%m%d-%H%M}.tar.gz"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes, mode: int = 0o644, mtime: float | None = None) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = mode
    info.mtime = int(mtime if mtime is not None else time.time())
    info.uname = info.gname = ""
    tar.addfile(info, io.BytesIO(data))


def write_archive(
    dest_dir: Path,
    home: Path,
    meta: ExportMeta,
    collection: Collection,
    dconf_dumps: list[DconfDump],
    package_lists: dict[str, PackageList],
    progress: Progress | None = None,
) -> Path:
    """Write the archive into `dest_dir` and return its path. Written atomically (temp + rename)."""
    for cat in meta.categories:
        if cat["id"].startswith(EXTRA_PREFIX) and not valid_extra_name(cat["id"][len(EXTRA_PREFIX) :]):
            raise ArchiveError(f"invalid extra folder name: {cat['id']}")
    for f in collection.files:
        check_rel(f.rel)

    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / archive_name(meta.de.get("id", "unknown"), meta.hostname)
    tmp = target.with_name(target.name + ".part")
    total = len(collection.files) + len(dconf_dumps) + len(package_lists)
    done = 0

    def tick() -> None:
        nonlocal done
        done += 1
        if progress:
            progress(done, total)

    manifest: dict = {
        "format": FORMAT,
        "dotde_version": __version__,
        "created": datetime.now().astimezone().isoformat(timespec="seconds"),
        "distro": meta.distro,
        "de": meta.de,
        "user": meta.user,
        "hostname": meta.hostname,
        "home": meta.home or str(home),
        "categories": meta.categories,
        "files": [],
        "dconf": [],
        "packages": {},
    }
    try:
        with tarfile.open(tmp, "w:gz") as tar:
            for f in collection.files:
                src = home / f.rel
                data = src.read_bytes()
                _add_bytes(tar, f"files/{f.rel}", data, f.mode, src.stat().st_mtime)
                manifest["files"].append(
                    {"path": f.rel, "category": f.category, "size": len(data), "mode": f.mode, "sha256": _sha256(data)}
                )
                tick()
            counters: dict[str, int] = {}
            for d in dconf_dumps:
                n = counters[d.category] = counters.get(d.category, 0) + 1
                name = f"dconf/{d.category}/{n}.ini"
                data = d.data.encode()
                _add_bytes(tar, name, data)
                manifest["dconf"].append({"category": d.category, "path": d.path, "file": name, "sha256": _sha256(data)})
                tick()
            for key, pl in package_lists.items():
                name = f"packages/{ARCHIVE_FILES[key]}"
                data = serialize(pl).encode()
                _add_bytes(tar, name, data)
                entry = {"source": pl.source, "file": name, "count": len(pl.packages), "sha256": _sha256(data)}
                if pl.source == "flatpak":
                    rname = f"packages/{FLATPAK_REMOTES_FILE}"
                    rdata = serialize_remotes(pl.remotes).encode()
                    _add_bytes(tar, rname, rdata)
                    entry["remotes_file"], entry["remotes_sha256"] = rname, _sha256(rdata)
                manifest["packages"][key] = entry
                tick()
            _add_bytes(tar, MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=False).encode())
        os.replace(tmp, target)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return target


# --- reading -----------------------------------------------------------------------------------


@dataclass
class OpenedArchive:
    path: Path
    workdir: Path  # extracted content
    manifest: dict

    def file_bytes(self, member: str) -> bytes:
        return (self.workdir / member).read_bytes()

    def text(self, member: str) -> str:
        return self.file_bytes(member).decode("utf-8")

    def cleanup(self) -> None:
        shutil.rmtree(self.workdir, ignore_errors=True)


def _check_member(m: tarfile.TarInfo) -> None:
    name = m.name
    if not (m.isfile() or m.isdir()):
        raise ArchiveError(f"unsupported member type (link or device): {name}")
    if name.startswith("/") or "\\" in name or "\x00" in name:
        raise ArchiveError(f"invalid member name: {name}")
    parts = PurePosixPath(name).parts
    if not parts or any(p in ("..", ".") for p in parts):
        raise ArchiveError(f"member name escapes the archive: {name}")
    top = parts[0]
    if m.isdir():
        if top not in ("files", "dconf", "packages"):
            raise ArchiveError(f"unexpected member: {name}")
        return
    if name == MANIFEST:
        return
    if top == "files":
        try:
            check_rel("/".join(parts[1:]))
        except PathError as exc:
            raise ArchiveError(str(exc)) from None
    elif top == "dconf":
        if len(parts) != 3 or not parts[2].endswith(".ini"):
            raise ArchiveError(f"unexpected member: {name}")
    elif top == "packages":
        if len(parts) != 2 or parts[1] not in (*ARCHIVE_FILES.values(), FLATPAK_REMOTES_FILE):
            raise ArchiveError(f"unexpected member: {name}")
    else:
        raise ArchiveError(f"unexpected member: {name}")


def _validate_manifest(manifest: dict) -> None:
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise ArchiveError("unsupported or missing archive format version")
    for key, kind in (("de", dict), ("distro", dict), ("categories", list), ("files", list),
                      ("dconf", list), ("packages", dict), ("home", str), ("user", str)):
        if not isinstance(manifest.get(key), kind):
            raise ArchiveError(f"manifest field '{key}' missing or invalid")
    if not valid_home(manifest["home"]):
        # It drives the path rewriting: "/usr" would turn every /usr path into the new home
        raise ArchiveError(f"invalid home folder in manifest: {manifest['home']!r}")
    for cat in manifest["categories"]:
        cid = cat.get("id", "") if isinstance(cat, dict) else ""
        if not isinstance(cid, str) or not cid:
            raise ArchiveError("manifest category without id")
        if cid.startswith(EXTRA_PREFIX) and not valid_extra_name(cid[len(EXTRA_PREFIX) :]):
            raise ArchiveError(f"invalid extra folder name in manifest: {cid}")
    for d in manifest["dconf"]:
        if not isinstance(d, dict) or not all(isinstance(d.get(k), str) for k in ("category", "path", "file", "sha256")):
            raise ArchiveError("manifest dconf entry invalid")
        if not _DCONF_RE.match(d["path"]):
            raise ArchiveError(f"invalid dconf path in manifest: {d['path']}")
    for key, entry in manifest["packages"].items():
        if key not in ARCHIVE_FILES or not isinstance(entry, dict):
            raise ArchiveError(f"unknown package list in manifest: {key}")
        if entry.get("file") != f"packages/{ARCHIVE_FILES[key]}" or not isinstance(entry.get("source"), str):
            raise ArchiveError(f"invalid package entry in manifest: {key}")
    for f in manifest["files"]:
        if not isinstance(f, dict) or not all(isinstance(f.get(k), str) for k in ("path", "category", "sha256")):
            raise ArchiveError("manifest file entry invalid")
        try:
            check_rel(f["path"])
        except PathError as exc:
            raise ArchiveError(str(exc)) from None


def valid_home(path: str) -> bool:
    """An absolute folder with at least two components (/home/x, /var/home/x), no '.' or '..'."""
    parts = PurePosixPath(path).parts
    return (
        path.startswith("/") and "\x00" not in path and len(parts) >= 3
        and not any(p in (".", "..") for p in parts)
    )


def free_space(path: Path) -> int:
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def read_archive(path: Path, workroot: Path) -> OpenedArchive:
    """Validate every member, extract one by one into a fresh folder under `workroot`, verify hashes.

    `workroot` should be on the same filesystem as the home (not /tmp, which may be RAM).
    """
    try:
        tar = tarfile.open(path, "r:gz")
    except (OSError, tarfile.TarError) as exc:
        raise ArchiveError(f"cannot open archive: {exc}") from None
    with tar:
        members = tar.getmembers()
        for m in members:
            _check_member(m)
        names = [m.name for m in members if m.isfile()]
        if len(names) != len(set(names)):
            raise ArchiveError("archive contains duplicate members")
        if MANIFEST not in names:
            raise ArchiveError("manifest.json missing: not a DotDE archive")
        needed = sum(m.size for m in members) + 1024 * 1024
        workroot.mkdir(parents=True, exist_ok=True)
        if free_space(workroot) < needed:
            raise ArchiveError(f"not enough free space to extract the archive ({needed // (1024 * 1024)} MB needed)")

        workdir = Path(tempfile.mkdtemp(prefix="import-", dir=workroot))
        try:
            for m in members:
                dest = workdir / m.name
                if m.isdir():
                    dest.mkdir(parents=True, exist_ok=True)
                    continue
                if m.name == MANIFEST and m.size > MAX_MANIFEST:
                    raise ArchiveError("manifest.json too large")
                src = tar.extractfile(m)
                if src is None:
                    raise ArchiveError(f"cannot read member: {m.name}")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with open(dest, "xb") as out:  # "x": never follow or overwrite anything
                    shutil.copyfileobj(src, out)
                os.chmod(dest, 0o600)
            try:
                manifest = json.loads((workdir / MANIFEST).read_text("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ArchiveError(f"manifest.json is not valid JSON: {exc}") from None
            _validate_manifest(manifest)
            _verify_hashes(workdir, manifest, set(names))
        except BaseException:
            shutil.rmtree(workdir, ignore_errors=True)
            raise
    return OpenedArchive(path, workdir, manifest)


def _verify_hashes(workdir: Path, manifest: dict, names: set[str]) -> None:
    expected: dict[str, str] = {f"files/{f['path']}": f["sha256"] for f in manifest["files"]}
    for d in manifest["dconf"]:
        expected[d["file"]] = d["sha256"]
    for entry in manifest["packages"].values():
        expected[entry["file"]] = entry["sha256"]
        if "remotes_file" in entry:
            expected[entry["remotes_file"]] = entry["remotes_sha256"]
    unlisted = names - set(expected) - {MANIFEST}
    if unlisted:
        raise ArchiveError(f"archive members not listed in the manifest: {sorted(unlisted)[:3]}")
    for member, digest in expected.items():
        if member not in names:
            raise ArchiveError(f"file listed in the manifest but missing: {member}")
        if _sha256((workdir / member).read_bytes()) != digest:
            raise ArchiveError(f"checksum mismatch: {member}")
