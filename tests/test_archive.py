import io
import json
import tarfile

import pytest

from dotde.archive import ArchiveError, DconfDump, ExportMeta, archive_name, read_archive, write_archive
from dotde.collect import collect, extra_category
from dotde.packages import Package, PackageList, Remote
from dotde.profiles import load_profile


def write(home, rel, data=b"x"):
    p = home / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


def meta(**over):
    m = ExportMeta(
        distro={"id": "cachyos", "id_like": ["arch"], "family": "arch", "pretty_name": "CachyOS"},
        de={"id": "kde", "name": "KDE Plasma", "version": "6.8.2"},
        categories=[{"id": "windows", "profile": "kde"}, {"id": "extra:fish", "profile": "extra"}],
        user="tester", hostname="box",
    )
    for k, v in over.items():
        setattr(m, k, v)
    return m


@pytest.fixture
def archive(home, tmp_path):
    write(home, ".config/kwinrc", b"[Windows]\nPlacement=Centered\n")
    write(home, ".config/fish/config.fish", b"set -x A 1\n")
    cats = [load_profile("kde").category("windows"), extra_category("fish")]
    coll = collect(home, cats, [])
    pkgs = {
        "native": PackageList("pacman", [Package("firefox")]),
        "flatpak": PackageList("flatpak", [Package("org.kde.kdenlive", "flathub", "system")],
                               [Remote("flathub", "https://dl.flathub.org/repo/", "system")]),
    }
    dumps = [DconfDump("appearance", "/org/gnome/desktop/interface/", "[/]\na=1\n")]
    return write_archive(tmp_path / "out", home, meta(), coll, dumps, pkgs)


def test_archive_name():
    from datetime import datetime
    assert archive_name("kde", "my box!", datetime(2026, 11, 6, 17, 5)) == "dotde-kde-my-box-20261106-1705.tar.gz"


def test_write_archive_layout(archive, home):
    with tarfile.open(archive) as tar:
        names = set(tar.getnames())
        manifest = json.load(tar.extractfile("manifest.json"))
    assert {"manifest.json", "files/.config/kwinrc", "files/.config/fish/config.fish",
            "dconf/appearance/1.ini", "packages/native.txt", "packages/flatpak.txt",
            "packages/flatpak-remotes.txt"} <= names
    assert {f["path"]: f["category"] for f in manifest["files"]} == {
        ".config/kwinrc": "windows", ".config/fish/config.fish": "extra:fish"}
    assert manifest["home"] == str(home) and manifest["user"] == "tester" and manifest["hostname"] == "box"
    assert manifest["packages"]["native"]["source"] == "pacman"
    assert not list(archive.parent.glob("*.part"))


def test_write_refuses_bad_extra(home, tmp_path):
    from dotde.collect import Collection
    with pytest.raises(ArchiveError):
        write_archive(tmp_path, home, meta(categories=[{"id": "extra:../.local/bin"}]), Collection(), [], {})


def test_read_valid_archive(archive, home):
    opened = read_archive(archive, home / ".local/state/dotde/tmp")
    try:
        assert opened.manifest["de"]["id"] == "kde"
        assert opened.file_bytes("files/.config/kwinrc").startswith(b"[Windows]")
        assert opened.workdir.is_relative_to(home / ".local/state/dotde/tmp")
    finally:
        opened.cleanup()
    assert not opened.workdir.exists()


def test_read_without_data_filter(archive, home, monkeypatch):
    monkeypatch.delattr(tarfile, "data_filter", raising=False)
    read_archive(archive, home / "w").cleanup()


# --- manipulated archives --------------------------------------------------------------------

def rebuild(src, dst, edit_members=None, edit_manifest=None, extra=()):
    """Copy an archive, optionally changing the manifest or adding members."""
    with tarfile.open(src) as tin, tarfile.open(dst, "w:gz") as tout:
        for m in tin.getmembers():
            data = tin.extractfile(m).read() if m.isfile() else None
            if m.name == "manifest.json" and edit_manifest:
                man = json.loads(data)
                edit_manifest(man)
                data = json.dumps(man).encode()
                m.size = len(data)
            if edit_members and edit_members(m, data) is False:
                continue
            tout.addfile(m, io.BytesIO(data) if data is not None else None)
        for info, data in extra:
            tout.addfile(info, io.BytesIO(data) if data is not None else None)
    return dst


def member(name, data=b"x", type_=tarfile.REGTYPE, linkname=""):
    info = tarfile.TarInfo(name)
    info.type, info.linkname = type_, linkname
    info.size = len(data) if type_ == tarfile.REGTYPE else 0
    return info, (data if type_ == tarfile.REGTYPE else None)


@pytest.mark.parametrize("bad", [
    member("files/../../.bashrc"),
    member("/etc/passwd"),
    member("files/.bashrc"),
    member("files/.local/bin/ls"),
    member("files/.config/link", type_=tarfile.SYMTYPE, linkname="/etc/passwd"),
    member("files/.config/hard", type_=tarfile.LNKTYPE, linkname="files/.config/kwinrc"),
    member("files/.config/dev", type_=tarfile.CHRTYPE),
    member("packages/evil.sh"),
])
def test_manipulated_members_rejected(archive, tmp_path, home, bad):
    dst = rebuild(archive, tmp_path / "bad.tar.gz", extra=[bad])
    with pytest.raises(ArchiveError):
        read_archive(dst, home / "w")
    assert not any((home / "w").glob("import-*"))


def test_unlisted_member_rejected(archive, tmp_path, home):
    dst = rebuild(archive, tmp_path / "bad.tar.gz", extra=[member("files/.config/sneaky")])
    with pytest.raises(ArchiveError, match="not listed"):
        read_archive(dst, home / "w")


def test_checksum_mismatch(archive, tmp_path, home):
    def edit(man):
        man["files"][0]["sha256"] = "0" * 64
    with pytest.raises(ArchiveError, match="checksum"):
        read_archive(rebuild(archive, tmp_path / "b.tar.gz", edit_manifest=edit), home / "w")


def test_missing_manifest(archive, tmp_path, home):
    dst = rebuild(archive, tmp_path / "b.tar.gz", edit_members=lambda m, d: m.name != "manifest.json")
    with pytest.raises(ArchiveError, match="manifest"):
        read_archive(dst, home / "w")


@pytest.mark.parametrize("extra_id", ["extra:../.local/bin", "extra:plasma-workspace", "extra:a/b", "extra:.."])
def test_bad_extra_names_in_manifest(archive, tmp_path, home, extra_id):
    def edit(man):
        man["categories"].append({"id": extra_id})
    with pytest.raises(ArchiveError, match="extra"):
        read_archive(rebuild(archive, tmp_path / "b.tar.gz", edit_manifest=edit), home / "w")


def test_not_enough_space(archive, home, monkeypatch):
    import dotde.archive as mod
    monkeypatch.setattr(mod, "free_space", lambda p: 10)
    with pytest.raises(ArchiveError, match="space"):
        read_archive(archive, home / "w")
    assert not any((home / "w").glob("import-*"))


def test_not_an_archive(tmp_path, home):
    f = tmp_path / "x.tar.gz"
    f.write_bytes(b"hello")
    with pytest.raises(ArchiveError):
        read_archive(f, home / "w")


@pytest.mark.parametrize("bad_home", ["/usr", "/", "rel/x", "/home/../etc", "/etc"])
def test_bad_home_in_manifest(archive, tmp_path, home, bad_home):
    def edit(man):
        man["home"] = bad_home
    with pytest.raises(ArchiveError, match="home"):
        read_archive(rebuild(archive, tmp_path / "b.tar.gz", edit_manifest=edit), home / "w")


@pytest.mark.parametrize("good_home", ["/home/mario", "/var/home/mario", "/home/d'angelo rossi"])
def test_good_home(good_home):
    from dotde.archive import valid_home
    assert valid_home(good_home)
