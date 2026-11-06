"""dconf dump/load per path (GNOME settings)."""

import os
import shutil
import subprocess
from pathlib import Path


class DconfError(RuntimeError):
    pass


def available() -> bool:
    return shutil.which("dconf") is not None


def _env() -> dict[str, str] | None:
    """Environment for dconf: from a TTY the session bus address may be missing."""
    if os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
        return None
    bus = Path(f"/run/user/{os.getuid()}/bus")
    if bus.exists():
        return {**os.environ, "DBUS_SESSION_BUS_ADDRESS": f"unix:path={bus}"}
    return None


def can_load() -> bool:
    """dconf writes go through dconf-service on the session bus."""
    return available() and (bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")) or _env() is not None)


def dump(path: str) -> str:
    try:
        proc = subprocess.run(["dconf", "dump", path], capture_output=True, text=True, env=_env(), check=False)
    except OSError as exc:
        raise DconfError(str(exc)) from None
    if proc.returncode != 0:
        raise DconfError(proc.stderr.strip() or f"dconf dump {path} failed")
    return proc.stdout


def load(path: str, data: str) -> None:
    try:
        proc = subprocess.run(
            ["dconf", "load", path], input=data, capture_output=True, text=True, env=_env(), check=False
        )
    except OSError as exc:
        raise DconfError(str(exc)) from None
    if proc.returncode != 0:
        raise DconfError(proc.stderr.strip() or f"dconf load {path} failed")


def reset(path: str) -> None:
    """Remove every key below `path` (used before reloading a backup on undo)."""
    try:
        proc = subprocess.run(["dconf", "reset", "-f", path], capture_output=True, text=True, env=_env(), check=False)
    except OSError as exc:
        raise DconfError(str(exc)) from None
    if proc.returncode != 0:
        raise DconfError(proc.stderr.strip() or f"dconf reset {path} failed")
