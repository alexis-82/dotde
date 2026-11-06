import pytest

from dotde.profiles import (
    ProfileError,
    available_profiles,
    combined_categories,
    load_common,
    load_profile,
    parse_profile,
)


def make(**over):
    data = {
        "meta": {"id": "test", "name": "Test", "restore_mode": "immediate"},
        "category": [
            {"id": "look", "label": {"en": "Look", "it": "Aspetto"}, "paths": ["~/.config/lookrc"]},
            {"id": "keys", "label": {"en": "Keys"}, "paths": ["~/.config/keys/"]},
        ],
    }
    data.update(over)
    return data


def test_valid_profile():
    p = parse_profile(make())
    assert p.id == "test"
    assert [c.id for c in p.categories] == ["look", "keys"]
    assert p.categories[1].paths == [".config/keys/"]


def test_missing_field():
    data = make()
    del data["meta"]["id"]
    with pytest.raises(ProfileError, match="missing field 'id'"):
        parse_profile(data)


def test_duplicate_category():
    data = make()
    data["category"][1]["id"] = "look"
    with pytest.raises(ProfileError, match="duplicate"):
        parse_profile(data)


@pytest.mark.parametrize("path", ["~/.bashrc", "~/.local/bin/x", "~/.config/../.bashrc", "/etc/passwd", "~/.local/"])
def test_forbidden_paths(path):
    data = make()
    data["category"][0]["paths"] = [path]
    with pytest.raises(ProfileError):
        parse_profile(data)


def test_unknown_restore_mode():
    data = make()
    data["meta"]["restore_mode"] = "magic"
    with pytest.raises(ProfileError, match="restore_mode"):
        parse_profile(data)


def test_dconf_overlap_between_categories():
    data = make(category=[
        {"id": "look", "label": {"en": "Look"}, "dconf": ["/org/gnome/desktop/"]},
        {"id": "keys", "label": {"en": "Keys"}, "dconf": ["/org/gnome/desktop/wm/keybindings/"]},
    ])
    with pytest.raises(ProfileError, match="overlap"):
        parse_profile(data)


def test_file_overlap_between_categories():
    data = make()
    data["category"][1]["paths"] = ["~/.config/"]
    with pytest.raises(ProfileError):  # ~/.config/ whole contains the blacklist too
        parse_profile(data)
    data["category"][1]["paths"] = ["~/.config/keys/", "~/.config/lookrc"]
    with pytest.raises(ProfileError, match="overlap"):
        parse_profile(data)


def test_bad_exclude_pattern():
    with pytest.raises(ProfileError):
        parse_profile(make(exclude=["*.pem"]))


@pytest.mark.parametrize("pid", ["kde", "gnome", "xfce", "hyprland", "sway"])
def test_shipped_profiles_load_and_combine_with_common(pid):
    p = load_profile(pid)
    assert p.categories
    combined_categories(p, load_common())


def test_available_profiles():
    assert set(available_profiles()) == {"kde", "gnome", "xfce", "hyprland", "sway"}


def test_unknown_profile():
    with pytest.raises(ProfileError):
        load_profile("../etc")
    with pytest.raises(ProfileError):
        load_profile("cinnamon")


def test_common_categories_not_excluded():
    from dotde.paths import is_excluded

    common = load_common()
    for pid in available_profiles():
        for cat in combined_categories(load_profile(pid), common):
            for p in cat.paths:
                assert not is_excluded(p, common.all_excludes, is_dir=p.endswith("/")), (pid, p)


def test_known_secrets_are_excluded():
    from dotde.paths import is_excluded

    excl = load_common().all_excludes
    assert is_excluded(".config/gh/hosts.yml", excl)
    assert is_excluded(".config/kdeconnect/privateKey.pem", excl)
    assert is_excluded(".config/Code/User/globalStorage/state.vscdb", excl)
    assert is_excluded(".config/Code/CachedData/x", excl)
    assert not is_excluded(".config/kwinrc", excl)


def test_unknown_key_rejected():
    data = make()
    data["category"][1]["exclude"] = ["~/.config/x"]  # misplaced top-level key
    with pytest.raises(ProfileError, match="unknown field"):
        parse_profile(data)
