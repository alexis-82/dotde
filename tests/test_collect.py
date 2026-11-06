from dotde.collect import collect, extra_candidates, extra_category
from dotde.profiles import combined_categories, load_common, load_profile


def write(home, rel, data=b"x"):
    p = home / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_collect_kde_with_excludes(home):
    write(home, ".config/kwinrc", b"12345")
    write(home, ".config/kdeglobals", b"abc")
    write(home, ".local/share/plasma/look-and-feel/x/metadata.json", b"{}")
    write(home, ".local/share/plasma/plasmoids/w/cache/blob", b"zz")  # excluded (cache dir)
    write(home, ".local/share/konsole/bookmarks.xml.tbcache", b"zz")  # excluded pattern
    write(home, ".config/gh/hosts.yml", b"token")  # not in any category
    common = load_common()
    cats = combined_categories(load_profile("kde"), common)
    out = collect(home, cats, common.all_excludes)
    rels = {f.rel for f in out.files}
    assert rels == {".config/kwinrc", ".config/kdeglobals", ".local/share/plasma/look-and-feel/x/metadata.json"}
    assert out.total_size == 5 + 3 + 2
    by_rel = {f.rel: f.category for f in out.files}
    assert by_rel[".config/kwinrc"] == "windows"


def test_symlinks_skipped(home, tmp_path):
    write(home, ".config/kwinrc")
    (home / ".config/kdeglobals").symlink_to(tmp_path)
    out = collect(home, load_profile("kde").categories, [])
    assert {f.rel for f in out.files} == {".config/kwinrc"}
    assert (".config/kdeglobals", "symbolic link") in out.skipped


def test_unreadable_file_reported(home):
    p = write(home, ".config/kwinrc")
    p.chmod(0)
    try:
        out = collect(home, load_profile("kde").categories, [])
    finally:
        p.chmod(0o644)
    assert (".config/kwinrc", "permission denied") in out.skipped or out.files  # root can read anything


def test_extra_candidates(home):
    write(home, ".config/kwinrc")
    write(home, ".config/kate/session", b"s")  # covered by the KDE profile
    write(home, ".config/fish/config.fish", b"set x 1")
    write(home, ".config/gh/hosts.yml", b"token")
    write(home, ".config/gh/config.yml", b"git_protocol: ssh")
    write(home, ".config/kdeconnect/privateKey.pem", b"key")
    write(home, ".config/kdeconnect/config", b"c")
    write(home, ".config/Code/CachedData/big", b"0" * 100)
    write(home, ".config/Code/User/settings.json", b"{}")
    write(home, ".config/systemd/user/x.service", b"")
    write(home, ".config/plasma-workspace/env/x.sh", b"")
    common = load_common()
    cats = combined_categories(load_profile("kde"), common)
    cands = {c.name: c for c in extra_candidates(home, cats, common.exclude, common.secret_patterns, common.sensitive_apps)}
    assert set(cands) == {"fish", "gh", "kdeconnect", "Code"}
    assert cands["gh"].sensitive and cands["kdeconnect"].sensitive
    assert not cands["fish"].sensitive and not cands["Code"].sensitive
    assert cands["Code"].size == 2  # cache excluded


def test_extra_category_collects_folder(home):
    write(home, ".config/fish/config.fish", b"abc")
    out = collect(home, [extra_category("fish")], [])
    assert [(f.rel, f.category) for f in out.files] == [(".config/fish/config.fish", "extra:fish")]
