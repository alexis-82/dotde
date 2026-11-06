"""Installed package lists and reinstall commands.

One adapter per source: the native manager of the distribution family (pacman, apt, dnf,
zypper) plus AUR, Flatpak and Snap. Package names read from an archive are untrusted: every
name is validated before it can reach a command line, and commands are argument lists
(never a shell string).
"""

import re
import shutil
import subprocess
from dataclasses import dataclass, field

# --- validation --------------------------------------------------------------------------------

_NAME_RULES = {
    "pacman": re.compile(r"^[a-z0-9@_+][a-z0-9@._+-]*$"),
    "aur": re.compile(r"^[a-z0-9@_+][a-z0-9@._+-]*$"),
    "apt": re.compile(r"^[a-z0-9][a-z0-9.+-]*(:[a-z0-9-]+)?$"),
    "dnf": re.compile(r"^[A-Za-z0-9_+][A-Za-z0-9._+-]*$"),
    "zypper": re.compile(r"^[A-Za-z0-9_+][A-Za-z0-9._+-]*$"),
    "flatpak": re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z0-9_-]+){2,}$"),
    "snap": re.compile(r"^[a-z0-9][a-z0-9-]*$"),
}
_REMOTE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
_URL_RE = re.compile(r"^https://[A-Za-z0-9._~:/?#\[\]@!$&()*+,;=%-]+$")
INSTALLATIONS = ("user", "system")
MAX_NAME = 200


def valid_name(source: str, name: str) -> bool:
    rule = _NAME_RULES.get(source)
    return bool(rule and len(name) <= MAX_NAME and rule.match(name))


def valid_remote(name: str) -> bool:
    return len(name) <= MAX_NAME and bool(_REMOTE_RE.match(name))


def valid_url(url: str) -> bool:
    return len(url) <= 2000 and bool(_URL_RE.match(url))


# --- data --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Package:
    name: str
    remote: str = ""  # flatpak
    installation: str = ""  # flatpak: user / system
    classic: bool = False  # snap


@dataclass(frozen=True)
class Remote:
    name: str
    url: str
    installation: str


@dataclass
class PackageList:
    source: str  # pacman / apt / dnf / zypper / aur / flatpak / snap
    packages: list[Package] = field(default_factory=list)
    remotes: list[Remote] = field(default_factory=list)  # flatpak only
    invalid: list[str] = field(default_factory=list)  # lines rejected while parsing


NATIVE_BY_FAMILY = {"arch": "pacman", "debian": "apt", "fedora": "dnf", "suse": "zypper"}
NATIVE_SOURCES = tuple(NATIVE_BY_FAMILY.values())
ARCHIVE_FILES = {"native": "native.txt", "aur": "aur.txt", "flatpak": "flatpak.txt", "snap": "snap.txt"}
FLATPAK_REMOTES_FILE = "flatpak-remotes.txt"


def _run(cmd: list[str], timeout: float = 120) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return ""
    return proc.stdout if proc.returncode == 0 else ""


# --- parsers of the package managers' output ------------------------------------------------------


def parse_lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip()]


def parse_dnf(text: str) -> list[str]:
    # dnf4 and dnf5 differ in how they print the query format: accept a literal "\n" too.
    names = []
    for chunk in text.replace("\\n", "\n").split():
        if chunk:
            names.append(chunk)
    return sorted(set(names))


def parse_zypper(text: str) -> list[str]:
    """`zypper search --installed-only`: 'i+' marks packages installed on user request."""
    names = []
    for line in text.splitlines():
        cols = [c.strip() for c in line.split("|")]
        if len(cols) >= 2 and cols[0] == "i+":
            names.append(cols[1])
    return names


def parse_flatpak_apps(text: str) -> list[Package]:
    pkgs = []
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) >= 3 and cols[0].strip():
            pkgs.append(Package(cols[0].strip(), remote=cols[1].strip(), installation=cols[2].strip()))
    return pkgs


def parse_flatpak_remotes(text: str) -> list[Remote]:
    remotes = []
    for line in text.splitlines():
        cols = line.split("\t")
        if len(cols) >= 2 and cols[0].strip():
            options = cols[2].split(",") if len(cols) >= 3 else []
            inst = "user" if "user" in options else "system"
            remotes.append(Remote(cols[0].strip(), cols[1].strip(), inst))
    return remotes


SNAP_SKIP_PREFIXES = ("core", "snapd", "bare", "gtk-common-themes", "gnome-")


def parse_snap(text: str) -> list[Package]:
    pkgs = []
    for i, line in enumerate(text.splitlines()):
        cols = line.split()
        if i == 0 or not cols:  # header: Name Version Rev Tracking Publisher Notes
            continue
        name = cols[0]
        if name.startswith(SNAP_SKIP_PREFIXES):
            continue
        notes = cols[5] if len(cols) >= 6 else ""
        pkgs.append(Package(name, classic="classic" in notes.split(",")))
    return pkgs


# --- listing on this system ----------------------------------------------------------------------


def aur_helper() -> str:
    for helper in ("paru", "yay"):
        if shutil.which(helper):
            return helper
    return ""


def source_available(source: str) -> bool:
    binary = {"pacman": "pacman", "aur": "pacman", "apt": "apt-mark", "dnf": "dnf",
              "zypper": "zypper", "flatpak": "flatpak", "snap": "snap"}.get(source)
    return bool(binary and shutil.which(binary))


def list_installed(source: str) -> PackageList:
    if source == "pacman":
        names = parse_lines(_run(["pacman", "-Qqen"]))
    elif source == "aur":
        names = parse_lines(_run(["pacman", "-Qqem"]))
    elif source == "apt":
        names = parse_lines(_run(["apt-mark", "showmanual"]))
    elif source == "dnf":
        names = parse_dnf(_run(["dnf", "repoquery", "--userinstalled", "--queryformat", "%{name}\\n"]))
    elif source == "zypper":
        names = parse_zypper(_run(["zypper", "--quiet", "--non-interactive", "search", "--installed-only", "--type", "package"]))
    elif source == "flatpak":
        apps = parse_flatpak_apps(_run(["flatpak", "list", "--app", "--columns=application,origin,installation"]))
        remotes = parse_flatpak_remotes(_run(["flatpak", "remotes", "--columns=name,url,options"]))
        return _validated(PackageList("flatpak", apps, remotes))
    elif source == "snap":
        return _validated(PackageList("snap", parse_snap(_run(["snap", "list"]))))
    else:
        raise ValueError(f"unknown package source: {source}")
    return _validated(PackageList(source, [Package(n) for n in names]))


def _validated(pl: PackageList) -> PackageList:
    good, bad = [], list(pl.invalid)
    for p in pl.packages:
        ok = valid_name(pl.source, p.name)
        if pl.source == "flatpak":
            ok = ok and valid_remote(p.remote) and p.installation in INSTALLATIONS
        (good if ok else bad).append(p if ok else p.name)
    remotes, bad_r = [], []
    for r in pl.remotes:
        ok = valid_remote(r.name) and valid_url(r.url) and r.installation in INSTALLATIONS
        (remotes if ok else bad_r).append(r if ok else r.name)
    return PackageList(pl.source, good, remotes, bad + bad_r)


# --- archive serialisation ---------------------------------------------------------------------


def serialize(pl: PackageList) -> str:
    lines = []
    for p in pl.packages:
        if pl.source == "flatpak":
            lines.append(f"{p.name}\t{p.remote}\t{p.installation}")
        elif pl.source == "snap":
            lines.append(f"{p.name}\t{'classic' if p.classic else ''}".rstrip("\t"))
        else:
            lines.append(p.name)
    return "\n".join(lines) + ("\n" if lines else "")


def serialize_remotes(remotes: list[Remote]) -> str:
    return "".join(f"{r.name}\t{r.url}\t{r.installation}\n" for r in remotes)


def parse_archive(source: str, text: str, remotes_text: str = "") -> PackageList:
    """Parse a package file from an archive. Invalid lines end up in `.invalid`, never in commands."""
    pkgs: list[Package] = []
    invalid: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        cols = line.split("\t")
        if source == "flatpak":
            if len(cols) != 3:
                invalid.append(line[:MAX_NAME])
                continue
            pkgs.append(Package(cols[0], remote=cols[1], installation=cols[2]))
        elif source == "snap":
            if len(cols) > 2 or (len(cols) == 2 and cols[1] not in ("", "classic")):
                invalid.append(line[:MAX_NAME])
                continue
            pkgs.append(Package(cols[0], classic=len(cols) == 2 and cols[1] == "classic"))
        else:
            if len(cols) != 1:
                invalid.append(line[:MAX_NAME])
                continue
            pkgs.append(Package(cols[0]))
    remotes = []
    for line in remotes_text.splitlines():
        cols = line.split("\t")
        if len(cols) == 3:
            remotes.append(Remote(*cols))
        elif line.strip():
            invalid.append(line[:MAX_NAME])
    return _validated(PackageList(source, pkgs, remotes, invalid))


# --- install commands --------------------------------------------------------------------------


def install_commands(pl: PackageList, existing_remotes: set[tuple[str, str]] | None = None) -> list[list[str]]:
    """Commands (argument lists) that reinstall a validated package list.

    `existing_remotes` is the set of (installation, remote name) already configured here.
    Names are always validated again: an invalid name never reaches a command.
    """
    names = [p.name for p in pl.packages if valid_name(pl.source, p.name)]
    if pl.source == "pacman":
        return [["sudo", "pacman", "-S", "--needed", "--", *names]] if names else []
    if pl.source == "aur":
        helper = aur_helper()
        return [[helper, "-S", "--needed", "--", *names]] if names and helper else []
    if pl.source == "apt":
        # apt-get has no "--" end-of-options marker: validation forbids a leading "-".
        return [["sudo", "apt-get", "install", *names]] if names else []
    if pl.source == "dnf":
        return [["sudo", "dnf", "install", "--", *names]] if names else []
    if pl.source == "zypper":
        # validation forbids a leading "-", as for apt-get.
        return [["sudo", "zypper", "install", *names]] if names else []
    if pl.source == "snap":
        cmds = []
        normal = [p.name for p in pl.packages if not p.classic and valid_name("snap", p.name)]
        if normal:
            cmds.append(["sudo", "snap", "install", "--", *normal])
        for p in pl.packages:  # snap accepts --classic for a single snap only
            if p.classic and valid_name("snap", p.name):
                cmds.append(["sudo", "snap", "install", "--classic", "--", p.name])
        return cmds
    if pl.source == "flatpak":
        existing = existing_remotes or set()
        cmds = []
        needed = {(p.installation, p.remote) for p in pl.packages}
        for r in pl.remotes:
            if (r.installation, r.name) in needed and (r.installation, r.name) not in existing:
                if valid_remote(r.name) and valid_url(r.url) and r.installation in INSTALLATIONS:
                    cmds.append(["flatpak", "remote-add", "--if-not-exists", f"--{r.installation}", "--", r.name, r.url])
        groups: dict[tuple[str, str], list[str]] = {}
        for p in pl.packages:
            if valid_name("flatpak", p.name) and valid_remote(p.remote) and p.installation in INSTALLATIONS:
                groups.setdefault((p.installation, p.remote), []).append(p.name)
        for (inst, remote), ids in sorted(groups.items()):
            cmds.append(["flatpak", "install", f"--{inst}", "--noninteractive", "--", remote, *ids])
        return cmds
    raise ValueError(f"unknown package source: {pl.source}")


def local_flatpak_remotes() -> set[tuple[str, str]]:
    if not shutil.which("flatpak"):
        return set()
    return {(r.installation, r.name) for r in parse_flatpak_remotes(_run(["flatpak", "remotes", "--columns=name,url,options"]))}
