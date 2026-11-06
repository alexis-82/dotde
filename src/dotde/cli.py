"""Entry point of the dotde command.

`dotde` starts the interactive interface. `--apply-pending` is internal: it is run by the
one-shot login script of a deferred restore, never by the user.
"""

import sys

MIN_PYTHON = (3, 11)


def main(argv: list[str] | None = None) -> int:
    if sys.version_info < MIN_PYTHON:
        # Checked before importing anything that needs tomllib (Python 3.11+).
        print(f"DotDE requires Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer "
              f"(found {sys.version_info.major}.{sys.version_info.minor}).", file=sys.stderr)
        return 1
    args = sys.argv[1:] if argv is None else argv

    from dotde import __version__
    from dotde.paths import home

    if args in (["--version"], ["-V"]):
        print(f"dotde {__version__}")
        return 0
    if args == ["--apply-pending"]:
        from dotde.pending import apply_pending

        return apply_pending(home())
    if args:
        print("usage: dotde", file=sys.stderr)
        return 2

    from dotde.ui import run

    return run()
