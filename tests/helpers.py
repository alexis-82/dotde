"""Shared helpers: build a real archive from a fake home."""

from pathlib import Path

from dotde.archive import DconfDump, ExportMeta, read_archive, write_archive
from dotde.collect import collect, extra_category
from dotde.detect import Distro, Environment
from dotde.packages import Package, PackageList
from dotde.profiles import load_common, load_profile


def write(home: Path, rel: str, data: bytes = b"x") -> Path:
    p = home / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def env(de="kde", family="arch") -> Environment:
    return Environment(Distro("cachyos", ["arch"], "CachyOS", family), de, de.upper(), "wayland")


def make_archive(src_home: Path, out: Path, de="kde", categories=("windows", "shortcuts"), extras=("fish",),
                 dumps=(), packages=None, user="olduser", host="oldbox", family="arch"):
    profile = load_profile(de)
    common = load_common()
    cats = [profile.category(c) or common.category(c) for c in categories] + [extra_category(e) for e in extras]
    coll = collect(src_home, cats, common.exclude, common.secret_patterns)
    meta = ExportMeta(
        distro={"id": "cachyos", "id_like": ["arch"], "family": family, "pretty_name": "CachyOS"},
        de={"id": de, "name": profile.name, "version": "6.8.2"},
        categories=[{"id": c.id, "profile": c.profile} for c in cats],
        user=user, hostname=host, home=str(src_home),
    )
    pkgs = packages if packages is not None else {"native": PackageList("pacman", [Package("firefox")])}
    return write_archive(out, src_home, meta, coll, [DconfDump(*d) for d in dumps], pkgs)


def open_archive(path: Path, home: Path):
    return read_archive(path, home / ".local/state/dotde/tmp")
