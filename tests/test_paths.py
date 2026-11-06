import os

import pytest

from dotde.paths import (
    PathError,
    atomic_write,
    check_rel,
    is_excluded,
    is_text,
    resolve_inside,
    rewrite_home,
)


@pytest.mark.parametrize(
    "rel", [".config/../.bashrc", ".bashrc", ".local/bin/ls", ".local/state/dotde/x", "/etc/passwd",
            ".config/plasma-workspace/env/x.sh", ".config/systemd/user/x.service", ""],
)
def test_check_rel_refuses(rel):
    with pytest.raises(PathError):
        check_rel(rel)


@pytest.mark.parametrize("rel", [".config/kwinrc", ".local/share/plasma/x", ".themes/T/index.theme", ".icons/I/"])
def test_check_rel_accepts(rel):
    check_rel(rel)


def test_symlink_escaping_root_refused(home, tmp_path):
    (home / ".config").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (home / ".config" / "evil").symlink_to(outside)
    with pytest.raises(PathError):
        resolve_inside(home, ".config/evil/file")


def test_symlinked_config_root_is_fine(home, tmp_path):
    real = tmp_path / "dotfiles-config"
    real.mkdir()
    (home / ".config").symlink_to(real)
    assert resolve_inside(home, ".config/kwinrc") == home / ".config/kwinrc"


def test_excludes():
    pats = ["~/.local/share/Trash/", "**/*[Cc]ache*/", "**/*.pem", "~/.config/a/*.log"]
    assert is_excluded(".local/share/Trash/files/x", pats)
    assert is_excluded(".config/Code/CachedData/x", pats)
    assert is_excluded(".config/x/cache", pats, is_dir=True)
    assert not is_excluded(".config/x/cache", pats)  # a *file* named cache is kept
    assert is_excluded(".config/kdeconnect/privateKey.pem", pats)
    assert is_excluded(".config/a/b.log", pats)
    assert not is_excluded(".config/kwinrc", pats)


def test_is_text():
    assert is_text(b"[General]\nName=x\n")
    assert not is_text(b"abc\x00def")
    assert not is_text(b"\xff\xfe\xfa")


def test_rewrite_home():
    data = b"a=/home/vecchio\nb=/home/vecchio/x\nc=/home/vecchiotto/y\nd=file:///home/vecchio/z\n"
    out = rewrite_home(data, "/home/vecchio", "/home/nuovo")
    assert out == b"a=/home/nuovo\nb=/home/nuovo/x\nc=/home/vecchiotto/y\nd=file:///home/nuovo/z\n"
    assert rewrite_home(data, "/home/vecchio", "/home/vecchio") == data


def test_atomic_write_keeps_original_on_failure(tmp_path, monkeypatch):
    target = tmp_path / "f.txt"
    target.write_bytes(b"original")

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        atomic_write(target, b"new content")
    assert target.read_bytes() == b"original"
    assert list(tmp_path.iterdir()) == [target]  # no temp file left behind


def test_atomic_write_mode(tmp_path):
    target = tmp_path / "sub" / "f"
    atomic_write(target, b"x", 0o600)
    assert target.read_bytes() == b"x"
    assert oct(target.stat().st_mode & 0o777) == "0o600"
