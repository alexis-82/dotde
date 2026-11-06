"""Is the desktop of a profile running for this user, which restore mode to use, how to log out."""

import os
import shutil
from pathlib import Path

from dotde.profiles import Profile

PROC = Path("/proc")
COMM_MAX = 15  # the kernel truncates /proc/<pid>/comm to 15 characters


def is_running(process: str, uid: int | None = None, proc: Path = PROC) -> bool:
    """True if a process named `process` runs with this user's UID (works from a TTY too)."""
    if not process:
        return False
    uid = os.getuid() if uid is None else uid
    wanted = process[:COMM_MAX]
    try:
        entries = list(proc.iterdir())
    except OSError:
        return False
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            if entry.stat().st_uid != uid:
                continue
            if (entry / "comm").read_text().strip() == wanted:
                return True
        except OSError:
            continue
    return False


def choose_mode(profile: Profile | None, running: bool) -> str:
    """immediate / deferred / offline, following the table in plan.md."""
    if profile is None or not running:
        return "immediate"
    return profile.restore_mode


def logout_command(profile: Profile | None) -> list[str] | None:
    if profile and profile.logout_cmd:
        cmd = list(profile.logout_cmd)
        if cmd[0] == "qdbus6" and not shutil.which("qdbus6") and shutil.which("qdbus"):
            cmd[0] = "qdbus"
        if shutil.which(cmd[0]):
            return cmd
    session_id = os.environ.get("XDG_SESSION_ID")
    if session_id and shutil.which("loginctl"):
        return ["loginctl", "terminate-session", session_id]
    return None
