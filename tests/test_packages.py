import pytest

from dotde import packages as pk
from dotde.packages import Package, PackageList, Remote


# --- Task 14/15/16: parsers -------------------------------------------------------------------

def test_parse_lines():
    assert pk.parse_lines("firefox\n\nlib32-mesa\n") == ["firefox", "lib32-mesa"]


def test_parse_dnf_both_formats():
    assert pk.parse_dnf("bash\nvim-enhanced\n") == ["bash", "vim-enhanced"]
    assert pk.parse_dnf("bash\\nvim-enhanced\\n") == ["bash", "vim-enhanced"]


def test_parse_zypper():
    out = (
        "S  | Name         | Summary          | Type\n"
        "---+--------------+------------------+--------\n"
        "i+ | MozillaFirefox | Browser        | package\n"
        "i  | libfoo1      | Library          | package\n"
        "i+ | vim          | Editor           | package\n"
    )
    assert pk.parse_zypper(out) == ["MozillaFirefox", "vim"]


def test_parse_flatpak():
    apps = pk.parse_flatpak_apps("org.kde.kdenlive\tflathub\tsystem\ncom.spotify.Client\tflathub\tuser\n")
    assert apps == [Package("org.kde.kdenlive", "flathub", "system"), Package("com.spotify.Client", "flathub", "user")]
    remotes = pk.parse_flatpak_remotes("flathub\thttps://dl.flathub.org/repo/\tsystem\nmine\thttps://x.org/repo/\tuser,filtered\n")
    assert remotes == [Remote("flathub", "https://dl.flathub.org/repo/", "system"), Remote("mine", "https://x.org/repo/", "user")]


def test_parse_snap():
    out = (
        "Name               Version  Rev   Tracking       Publisher   Notes\n"
        "core22             2024     1380  latest/stable  canonical✓  base\n"
        "code               1.9      170   latest/stable  vscode✓     classic\n"
        "firefox            130      4848  latest/stable  mozilla✓    -\n"
        "gnome-42-2204      0+git    176   latest/stable  canonical✓  -\n"
        "snapd              2.63     21759 latest/stable  canonical✓  snapd\n"
    )
    assert pk.parse_snap(out) == [Package("code", classic=True), Package("firefox")]


def test_native_by_family():
    assert pk.NATIVE_BY_FAMILY == {"arch": "pacman", "debian": "apt", "fedora": "dnf", "suse": "zypper"}


def test_aur_without_helper(monkeypatch):
    monkeypatch.setattr(pk.shutil, "which", lambda _: None)
    assert pk.aur_helper() == ""
    assert pk.install_commands(PackageList("aur", [Package("yay-bin")])) == []


def test_missing_command_is_not_an_error(monkeypatch):
    def boom(*a, **k):
        raise FileNotFoundError("snap")
    monkeypatch.setattr(pk.subprocess, "run", boom)
    monkeypatch.setattr(pk.shutil, "which", lambda _: None)
    assert not pk.source_available("snap")
    assert pk.list_installed("snap").packages == []


# --- Task 17: validation ----------------------------------------------------------------------

@pytest.mark.parametrize("name", ["--config=/tmp/x", "-Syu", "a b", "$(id)", "../x", "", "x;rm", "`id`"])
@pytest.mark.parametrize("source", ["pacman", "aur", "apt", "dnf", "zypper", "snap", "flatpak"])
def test_invalid_names(source, name):
    assert not pk.valid_name(source, name)


@pytest.mark.parametrize("source, name", [
    ("pacman", "firefox"), ("pacman", "lib32-mesa"), ("pacman", "gtk2+"), ("aur", "paru-bin"),
    ("apt", "libc6:i386"), ("apt", "g++"), ("dnf", "NetworkManager"), ("zypper", "MozillaFirefox"),
    ("flatpak", "org.kde.kdenlive"), ("flatpak", "com.github.tchx84.Flatseal"), ("snap", "code"),
])
def test_valid_names(source, name):
    assert pk.valid_name(source, name)


def test_remote_and_url_validation():
    assert pk.valid_remote("flathub-beta")
    assert not pk.valid_remote("--user")
    assert pk.valid_url("https://dl.flathub.org/repo/")
    assert not pk.valid_url("http://insecure.org/repo")
    assert not pk.valid_url("https://x.org/a b")
    assert not pk.valid_url("file:///etc")


def test_parse_archive_rejects_injection():
    pl = pk.parse_archive("pacman", "firefox\n--config=/tmp/x.conf\nvim\n")
    assert [p.name for p in pl.packages] == ["firefox", "vim"]
    assert pl.invalid == ["--config=/tmp/x.conf"]


def test_serialize_roundtrip():
    pl = PackageList("flatpak", [Package("org.kde.kdenlive", "flathub", "system")],
                     [Remote("flathub", "https://dl.flathub.org/repo/", "system")])
    back = pk.parse_archive("flatpak", pk.serialize(pl), pk.serialize_remotes(pl.remotes))
    assert back.packages == pl.packages and back.remotes == pl.remotes and not back.invalid
    snaps = PackageList("snap", [Package("code", classic=True), Package("firefox")])
    assert pk.parse_archive("snap", pk.serialize(snaps)).packages == snaps.packages


# --- install commands (used by Task 26) ----------------------------------------------------------

def test_install_pacman_uses_double_dash():
    cmds = pk.install_commands(PackageList("pacman", [Package("firefox"), Package("vim")]))
    assert cmds == [["sudo", "pacman", "-S", "--needed", "--", "firefox", "vim"]]


def test_install_snap_classic_one_per_command():
    pl = PackageList("snap", [Package("code", classic=True), Package("nvim", classic=True), Package("firefox")])
    assert pk.install_commands(pl) == [
        ["sudo", "snap", "install", "--", "firefox"],
        ["sudo", "snap", "install", "--classic", "--", "code"],
        ["sudo", "snap", "install", "--classic", "--", "nvim"],
    ]


def test_install_flatpak_groups_and_adds_missing_remote():
    pl = PackageList(
        "flatpak",
        [Package("org.a.App", "flathub", "system"), Package("org.b.App", "flathub", "user"),
         Package("org.c.App", "flathub", "system")],
        [Remote("flathub", "https://dl.flathub.org/repo/", "system"), Remote("flathub", "https://dl.flathub.org/repo/", "user")],
    )
    cmds = pk.install_commands(pl, existing_remotes={("user", "flathub")})
    assert cmds == [
        ["flatpak", "remote-add", "--if-not-exists", "--system", "--", "flathub", "https://dl.flathub.org/repo/"],
        ["flatpak", "install", "--system", "--noninteractive", "--", "flathub", "org.a.App", "org.c.App"],
        ["flatpak", "install", "--user", "--noninteractive", "--", "flathub", "org.b.App"],
    ]


def test_install_never_contains_invalid_names():
    pl = PackageList("pacman", [Package("firefox"), Package("--overwrite=*")])
    assert pk.install_commands(pl) == [["sudo", "pacman", "-S", "--needed", "--", "firefox"]]
