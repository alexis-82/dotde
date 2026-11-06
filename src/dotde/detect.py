"""Detection of distribution, distribution family, desktop environment and session type."""

import os
import shlex
from dataclasses import dataclass, field
from pathlib import Path

OS_RELEASE = Path("/etc/os-release")
FAMILIES = ("arch", "debian", "fedora", "suse")
UNKNOWN = "unknown"

# Normalised XDG_CURRENT_DESKTOP / DESKTOP_SESSION values -> profile id.
_DE_ALIASES = {
    "kde": "kde",
    "plasma": "kde",
    "plasmawayland": "kde",
    "gnome": "gnome",
    "gnome-xorg": "gnome",
    "gnome-wayland": "gnome",
    "xfce": "xfce",
    "xfce4": "xfce",
    "hyprland": "hyprland",
    "sway": "sway",
}


@dataclass
class Distro:
    id: str = UNKNOWN
    id_like: list[str] = field(default_factory=list)
    pretty_name: str = ""
    family: str = UNKNOWN


@dataclass
class Environment:
    distro: Distro
    de: str  # profile id or "unknown"
    de_raw: str  # raw XDG_CURRENT_DESKTOP value, for display
    session_type: str  # wayland / x11 / tty / unknown


def parse_os_release(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, raw = line.partition("=")
        try:
            parts = shlex.split(raw)
        except ValueError:
            parts = [raw.strip("\"'")]
        values[key.strip()] = parts[0] if parts else ""
    return values


def family_of(distro_id: str, id_like: list[str]) -> str:
    candidates = [distro_id, *id_like]
    for cand in candidates:
        cand = cand.lower()
        if cand in FAMILIES:
            return cand
        if cand in ("ubuntu",):
            return "debian"
        if cand in ("rhel", "centos"):
            return "fedora"
        if cand.startswith("opensuse") or cand == "sles":
            return "suse"
    return UNKNOWN


def detect_distro(path: Path = OS_RELEASE) -> Distro:
    try:
        values = parse_os_release(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return Distro()
    distro_id = values.get("ID", UNKNOWN).lower() or UNKNOWN
    id_like = values.get("ID_LIKE", "").lower().split()
    return Distro(
        id=distro_id,
        id_like=id_like,
        pretty_name=values.get("PRETTY_NAME", distro_id),
        family=family_of(distro_id, id_like),
    )


def normalise_de(value: str) -> str:
    """Map an XDG_CURRENT_DESKTOP-style value (possibly colon-separated) to a profile id."""
    for part in value.split(":"):
        key = part.strip().lower()
        if key in _DE_ALIASES:
            return _DE_ALIASES[key]
    return UNKNOWN


def detect_de(env: dict[str, str] | None = None) -> tuple[str, str]:
    env = os.environ if env is None else env
    for var in ("XDG_CURRENT_DESKTOP", "XDG_SESSION_DESKTOP", "DESKTOP_SESSION"):
        raw = env.get(var, "")
        if raw:
            de = normalise_de(Path(raw).name)
            if de != UNKNOWN:
                return de, raw
    return UNKNOWN, env.get("XDG_CURRENT_DESKTOP", "")


def detect_session_type(env: dict[str, str] | None = None) -> str:
    env = os.environ if env is None else env
    value = env.get("XDG_SESSION_TYPE", "").lower()
    if value in ("wayland", "x11", "tty"):
        return value
    if env.get("WAYLAND_DISPLAY"):
        return "wayland"
    if env.get("DISPLAY"):
        return "x11"
    return UNKNOWN


def detect_environment() -> Environment:
    de, raw = detect_de()
    return Environment(distro=detect_distro(), de=de, de_raw=raw, session_type=detect_session_type())
