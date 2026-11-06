import pytest

from dotde.detect import detect_de, detect_distro, detect_session_type

OS_RELEASES = {
    "cachyos": ('NAME="CachyOS Linux"\nID=cachyos\nID_LIKE=arch\nPRETTY_NAME="CachyOS"\n', "arch"),
    "ubuntu": ('NAME="Ubuntu"\nID=ubuntu\nID_LIKE=debian\nPRETTY_NAME="Ubuntu 24.04 LTS"\n', "debian"),
    "debian": ("ID=debian\nPRETTY_NAME='Debian GNU/Linux 12'\n", "debian"),
    "mint": ('ID=linuxmint\nID_LIKE="ubuntu debian"\n', "debian"),
    "fedora": ("ID=fedora\nPRETTY_NAME=\"Fedora Linux 41\"\n", "fedora"),
    "opensuse": ('ID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n', "suse"),
    "alien": ("ID=nixos\n", "unknown"),
}


@pytest.mark.parametrize("name", OS_RELEASES)
def test_distro_family(tmp_path, name):
    text, family = OS_RELEASES[name]
    f = tmp_path / "os-release"
    f.write_text(text)
    assert detect_distro(f).family == family


def test_distro_missing_file(tmp_path):
    d = detect_distro(tmp_path / "nope")
    assert d.family == "unknown" and d.id == "unknown"


@pytest.mark.parametrize(
    "value, expected",
    [("KDE", "kde"), ("GNOME", "gnome"), ("ubuntu:GNOME", "gnome"), ("XFCE", "xfce"),
     ("Hyprland", "hyprland"), ("sway", "sway"), ("X-Cinnamon", "unknown")],
)
def test_de(value, expected):
    assert detect_de({"XDG_CURRENT_DESKTOP": value})[0] == expected


def test_de_fallback_desktop_session():
    assert detect_de({"DESKTOP_SESSION": "/usr/share/xsessions/plasma"})[0] == "kde"


def test_de_no_variables():
    assert detect_de({}) == ("unknown", "")


def test_session_type():
    assert detect_session_type({"XDG_SESSION_TYPE": "wayland"}) == "wayland"
    assert detect_session_type({"DISPLAY": ":0"}) == "x11"
    assert detect_session_type({}) == "unknown"
