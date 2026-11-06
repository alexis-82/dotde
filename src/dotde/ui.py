"""Interactive terminal interface (questionary for questions, rich for output)."""

import os
import subprocess
import traceback
from dataclasses import asdict
from pathlib import Path

import questionary
from questionary.prompts.common import InquirerControl
from rich import box
from rich.console import Console, Group
from rich.markup import escape
from rich.panel import Panel
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text

from dotde import __version__, dconf, pending, restore
from dotde.archive import ArchiveError, DconfDump, ExportMeta, read_archive, write_archive
from dotde.collect import EXTRA_PREFIX, collect, extra_candidates, extra_category
from dotde.detect import Environment, detect_environment
from dotde.i18n import label, t
from dotde.packages import NATIVE_BY_FAMILY, list_installed, source_available
from dotde.paths import home, state_dir
from dotde.profiles import (
    Profile,
    ProfileError,
    available_profiles,
    combined_categories,
    de_version,
    load_common,
    load_profile,
)
from dotde.session import choose_mode, is_running, logout_command

console = Console(highlight=False)
SHOW_PACKAGES = 20


class Cancelled(Exception):
    """The user cancelled a question (Esc / Ctrl+C) or answered no to a confirmation."""


# --- small helpers ---------------------------------------------------------------------------------


def ask(question):
    try:
        answer = question.unsafe_ask()
    except KeyboardInterrupt:
        raise Cancelled from None
    if answer is None:
        raise Cancelled
    return answer


def confirm(text: str, default: bool = True) -> bool:
    return ask(questionary.confirm(text, default=default, style=STYLE))


def fmt_size(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{n} B"


def warn(text: str) -> None:
    console.print(f"[yellow]⚠ {escape(text)}[/]")


def info(text: str) -> None:
    console.print(f"[cyan]ℹ {escape(text)}[/]")


def error(text: str) -> None:
    console.print(f"[red]✗ {escape(text)}[/]")


def ok(text: str) -> None:
    console.print(f"[green]✓ {escape(text)}[/]")


def notice(n: restore.Notice) -> None:
    text = t(n.key, **n.params)
    (info if n.key.startswith("info.") else warn)(text)


def progress_bar() -> Progress:
    return Progress(TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), console=console)


def profile_name(profile: Profile | None) -> str:
    return profile.name if profile else t("ui.common_only")


# --- look and feel ---------------------------------------------------------------------------------

# The Linux text console (TTY, TERM=linux) has no emoji and few Unicode symbols: there the
# interface keeps the colours but drops the icons.
FANCY = os.environ.get("TERM", "") != "linux"

STYLE = questionary.Style([
    ("qmark", "fg:#c678dd bold"),
    ("question", "bold"),
    ("pointer", "fg:#61afef bold"),
    ("highlighted", "fg:#61afef bold"),
    ("selected", "fg:#98c379"),
    ("back", "fg:#abb2bf"),
    ("answer", "fg:#e5c07b bold"),
    ("instruction", "fg:#5c6370 italic"),
    ("disabled", "fg:#5c6370 italic"),
    ("icon", "fg:#56b6c2 bold"),
    ("exit", "fg:#e06c75"),
])
POINTER = "❯" if FANCY else ">"


def _selectable(choice) -> bool:
    return not choice.disabled and not isinstance(choice, questionary.Separator)


def _select_next(self) -> None:
    """Arrow down: go to the next selectable item, or stay on the last one (no wrap-around)."""
    for i in range(self.pointed_at + 1, self.choice_count):
        if _selectable(self.filtered_choices[i]):
            self.pointed_at = i
            return


def _select_previous(self) -> None:
    """Arrow up: go to the previous selectable item, or stay on the first one (no wrap-around)."""
    for i in range(self.pointed_at - 1, -1, -1):
        if _selectable(self.filtered_choices[i]):
            self.pointed_at = i
            return


_original_tokens = InquirerControl._get_choice_tokens


def _choice_tokens(self):
    """Like questionary's, but the "Back" entry of a checkbox list gets no tick box."""
    tokens = []
    for style, text in _original_tokens(self):
        if style == "class:back" and tokens and tokens[-1][1].strip() in ("○", "●"):
            tokens[-1] = ("class:text", " " * len(tokens[-1][1]))  # keep it aligned with the items
        tokens.append((style, text))
    return tokens


# questionary wraps around at the ends of a list; DotDE stops there instead.
InquirerControl.select_next = _select_next
InquirerControl.select_previous = _select_previous
InquirerControl._get_choice_tokens = _choice_tokens
BANNER_COLORS = ("#61afef", "#6aa6f0", "#8a8ff0", "#a77ff0", "#c678dd")


BACK = "__back__"  # answer of the "Back" entry


class GoBack(Exception):
    """The user chose "Back" on the first step of a flow: return to the main menu."""


def back_choice() -> questionary.Choice:
    return questionary.Choice([("class:back", ("← " if FANCY else "< ") + t("ui.back"))], BACK)


def with_back(choices: list) -> list:
    """Every submenu ends with an empty line and the "Back" entry."""
    return [*choices, questionary.Separator(" "), back_choice()]


def select(message, choices, back=False, **kw):
    if back:
        choices = with_back(choices)
    return questionary.select(message, choices=choices, style=STYLE, pointer=POINTER, **kw)


def _pad_titles(choices: list) -> list:
    """Same width for every text title, so the highlighted (checked) rows line up."""
    width = max((len(c.title) for c in choices if isinstance(c.title, str)), default=0)
    for c in choices:
        if isinstance(c.title, str):
            c.title = c.title.ljust(width)
    return choices


def checkbox(message, choices, back=False, **kw):
    choices = _pad_titles(list(choices))
    if back:
        choices = with_back(choices)
    kw.setdefault("instruction", "")  # hides questionary's "(Use arrow keys to move, <space> to select, …)"
    question = questionary.checkbox(message, choices=choices, style=STYLE, pointer=POINTER, **kw)
    if back:
        _bind_back(question)
    return question


def _bind_back(question) -> None:
    """In a checkbox list, Enter on "Back" goes back at once (no need to tick it), space does nothing."""
    from prompt_toolkit.filters import Condition
    from prompt_toolkit.keys import Keys

    control = next(c for c in question.application.layout.find_all_controls() if isinstance(c, InquirerControl))
    on_back = Condition(lambda: control.get_pointed_at().value == BACK)
    bindings = question.application.key_bindings

    @bindings.add(Keys.ControlM, eager=True, filter=on_back)
    def _(event):
        event.app.exit(result=BACK)

    @bindings.add(" ", eager=True, filter=on_back)
    def _(event):
        pass


def path_question(message, **kw):
    return questionary.path(message, style=STYLE, **kw)


def clear_screen() -> None:
    if console.is_terminal:
        console.clear()


def pause() -> None:
    """Let the user read the result of an operation before the screen is cleared."""
    if not console.is_terminal:
        return
    try:
        questionary.press_any_key_to_continue(t("ui.press_key"), style=STYLE).unsafe_ask()
    except KeyboardInterrupt:
        pass


# --- header and menu --------------------------------------------------------------------------------


def banner() -> Text:
    text = Text(justify="center")
    for i, ch in enumerate("DotDE"):
        text.append(ch, style=f"bold {BANNER_COLORS[i % len(BANNER_COLORS)]}")
    text.append(f"  v{__version__}", style="dim")
    text.append("\n" + t("ui.subtitle"), style="italic #abb2bf")
    return text


def show_header(env: Environment, profile: Profile | None, version: str) -> None:
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="bold #56b6c2", no_wrap=True)
    grid.add_column(style="#e5c07b")
    grid.add_row(t("ui.distro"), escape(env.distro.pretty_name or env.distro.id))
    de = profile.name if profile else (env.de_raw or t("ui.unknown"))
    grid.add_row(t("ui.desktop"), escape(f"{de} {version}".strip()))
    grid.add_row(t("ui.session"), escape(env.session_type))
    console.print(Panel(Group(banner(), Text(), grid), border_style="#c678dd",
                        box=box.ROUNDED if FANCY else box.ASCII, padding=(1, 3), expand=False))
    h = home()
    if pending.has_pending(h):
        warn(t("ui.pending_notice"))
    last = pending.last_apply(h)
    if last and last.get("status") == "error" and not last.get("seen"):
        error(t("ui.last_apply_failed", message=last.get("message", ""), log=str(pending.log_path(h))))
        pending.mark_last_apply_seen(h)
    console.print()


def menu_choice(icon: str, title: str, value: str, style: str = "", disabled: str | bool | None = None):
    parts = []
    if FANCY:
        parts.append(("class:icon", f"{icon}  "))
    parts.append((style, title))
    return questionary.Choice(parts, value, disabled=disabled)


def main_menu() -> str:
    h = home()
    if pending.has_pending(h):
        undo = menu_choice("↺", t("menu.cancel_pending"), "undo")
    elif restore.latest_backup(h):
        undo = menu_choice("↺", t("menu.undo"), "undo")
    else:
        undo = menu_choice("↺", t("menu.undo"), "undo", disabled=True)  # True: no reason shown
    return ask(select(t("menu.title"), [
        menu_choice("↑", t("menu.export"), "export"),
        menu_choice("↓", t("menu.import"), "import"),
        undo,
        # Placeholder: the update feature is not implemented yet (see tasks.md)
        menu_choice("↻", t("menu.update"), "update", disabled=t("menu.coming_soon")),
        questionary.Separator(" "),
        menu_choice("✕", t("menu.exit"), "exit", style="class:exit"),
    ], instruction=" "))  # a space hides questionary's default "(Use arrow keys)"


def run() -> int:
    env = detect_environment()
    try:
        profile = load_profile(env.de) if env.de != "unknown" else None
    except ProfileError:
        profile = None
    version = de_version(profile) if profile else ""
    flows = {"export": flow_export, "import": flow_import, "undo": flow_undo}
    while True:
        clear_screen()
        show_header(env, profile, version)
        try:
            choice = main_menu()
        except Cancelled:
            return 0
        if choice == "exit":
            return 0
        console.print()
        try:
            flows[choice](env)
        except GoBack:
            continue  # straight back to the menu, nothing to read
        except (Cancelled, KeyboardInterrupt):
            # Ctrl+C while DotDE is working (not inside a question): files are consistent
            # (atomic writes, backup journal), so it is just a cancellation.
            console.print()
            info(t("ui.cancelled"))
        except Exception as exc:  # noqa: BLE001 - never show a traceback to the user
            error(t("err.unexpected", error=f"{type(exc).__name__}: {exc}"))
            if os.environ.get("DOTDE_DEBUG"):
                traceback.print_exc()
        console.print()
        pause()


# --- export (Task 19) ------------------------------------------------------------------------------


def pick_profile(env: Environment) -> Profile | None:
    if env.de != "unknown":
        return load_profile(env.de)
    warn(t("export.de_unknown", de=env.de_raw or "?"))
    choices = [questionary.Choice(load_profile(p).name, p) for p in available_profiles()]
    choices.append(questionary.Choice(t("ui.common_only"), ""))
    pid = ask(select(t("export.pick_profile"), choices, back=True))
    if pid == BACK:
        raise GoBack
    return load_profile(pid) if pid else None


def choose_export(cats, candidates, sources) -> tuple[list[str], list[str], list[str]]:
    """The three selection steps of the export. "Back" returns to the previous step (keeping
    what was ticked there), or to the main menu from the first one."""
    suffix = f"  ({t('ui.common')})"
    answers: dict[int, list[str]] = {
        0: [c.id for c in cats],                    # categories: all ticked at first
        1: [],                                      # extra apps: none
        2: [key for key, _src, _title in sources],  # package lists: all
    }
    steps = [0, *([1] if candidates else []), *([2] if sources else [])]
    i = 0
    while i < len(steps):
        step = steps[i]
        if step == 0:
            question = checkbox(t("export.categories"), [
                questionary.Choice(label(c.label) + (suffix if c.profile == "common" else ""), c.id,
                                   checked=c.id in answers[0])
                for c in cats
            ], back=True)
        elif step == 1:
            question = checkbox(t("export.extras"), [
                questionary.Choice(
                    f"{c.name}  ({fmt_size(c.size)})" + (f"  ⚠ {t('export.sensitive')}" if c.sensitive else ""),
                    c.name, checked=c.name in answers[1])
                for c in candidates
            ], back=True)
        else:
            question = checkbox(t("export.packages"), [
                questionary.Choice(title, key, checked=key in answers[2]) for key, _src, title in sources
            ], back=True)
        answer = ask(question)
        if answer == BACK:
            if i == 0:
                raise GoBack
            i -= 1
            continue
        if step == 1:
            sensitive = [c.name for c in candidates if c.sensitive and c.name in answer]
            if sensitive and not confirm(t("export.sensitive_confirm", names=", ".join(sensitive)), default=False):
                answer = [e for e in answer if e not in sensitive]
        answers[step] = answer
        i += 1
    return answers[0], answers[1], answers[2] if sources else []


def flow_export(env: Environment) -> None:
    h = home()
    profile = pick_profile(env)
    common = load_common()
    cats = combined_categories(profile, common)

    with console.status(t("export.scanning_extras")):
        candidates = extra_candidates(h, cats, common.exclude, common.secret_patterns, common.sensitive_apps)
    native = NATIVE_BY_FAMILY.get(env.distro.family, "")
    sources = []
    if native and source_available(native):
        sources.append(("native", native, t("pkg.source.native", manager=native)))
    if env.distro.family == "arch" and source_available("aur"):
        sources.append(("aur", "aur", t("pkg.source.aur")))
    for key in ("flatpak", "snap"):
        if source_available(key):
            sources.append((key, key, t(f"pkg.source.{key}")))

    selected_ids, extras, chosen_sources = choose_export(cats, candidates, sources)
    selected = [c for c in cats if c.id in selected_ids]

    extra_cats = [extra_category(e) for e in extras]
    dconf_dumps: list[DconfDump] = []
    with console.status(t("export.collecting")):
        excludes = common.exclude + (profile.exclude if profile else [])
        coll = collect(h, selected + extra_cats, excludes, common.secret_patterns)
        wants_dconf = [c for c in selected if c.dconf]
        if wants_dconf and dconf.available():
            for c in wants_dconf:
                for path in c.dconf:
                    try:
                        dconf_dumps.append(DconfDump(c.id, path, dconf.dump(path)))
                    except dconf.DconfError as exc:
                        coll.skipped.append((path, str(exc)))
        package_lists = {key: list_installed(src) for key, src, _title in sources if key in chosen_sources}
    if wants_dconf and not dconf.available():
        warn(t("export.no_dconf"))

    table = Table(show_header=False, box=None, padding=(0, 2))
    table.add_row(t("export.sum_categories"), str(len(selected) + len(extra_cats)))
    table.add_row(t("export.sum_files"), f"{len(coll.files)}  ({fmt_size(coll.total_size)})")
    if dconf_dumps:
        table.add_row(t("export.sum_dconf"), str(len(dconf_dumps)))
    for key, pl in package_lists.items():
        table.add_row(t(f"pkg.source.{key}", manager=native), str(len(pl.packages)))
    console.print(table)
    if coll.skipped:
        warn(t("export.skipped", n=len(coll.skipped)))
        for rel, reason in coll.skipped[:5]:
            console.print(f"   [dim]{escape(rel)} — {escape(reason)}[/]")
    if not coll.files and not dconf_dumps and not any(pl.packages for pl in package_lists.values()):
        warn(t("export.nothing"))
        return

    dest = Path(os.path.expanduser(ask(path_question(t("export.dest"), default=str(h), only_directories=True))))
    if not confirm(t("export.confirm")):
        raise Cancelled

    categories = [{"id": c.id, "profile": c.profile, "label": c.label} for c in selected + extra_cats]
    meta = ExportMeta(
        distro=asdict(env.distro),
        de={"id": profile.id if profile else "unknown", "name": profile_name(profile),
            "version": de_version(profile) if profile else ""},
        categories=categories,
        home=str(h),
    )
    try:
        with progress_bar() as bar:
            task = bar.add_task(t("export.writing"), total=None)
            path = write_archive(dest, h, meta, coll, dconf_dumps, package_lists,
                                 progress=lambda d, tot: bar.update(task, completed=d, total=tot))
    except OSError as exc:
        error(t("err.write", path=str(dest), error=exc.strerror or str(exc)))
        return
    ok(t("export.done", path=str(path), size=fmt_size(path.stat().st_size)))
    info(t("export.hint"))


# --- import (Tasks 26, 29, 30) -------------------------------------------------------------------------


def find_archives(h: Path) -> list[Path]:
    found = []
    for folder in (h, h / "Downloads", h / "Scaricati"):
        try:
            found += sorted(folder.glob("dotde-*.tar.gz"), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            continue
    return found


def pick_archive(h: Path) -> Path:
    found = find_archives(h)
    if found:
        choices = [questionary.Choice(str(p), str(p)) for p in found[:10]]
        choices.append(questionary.Choice(t("import.other_path"), ""))
        picked = ask(select(t("import.pick_archive"), choices, back=True))
        if picked == BACK:
            raise GoBack
        if picked:
            return Path(picked)
    raw = ask(path_question(t("import.archive_path"), default=str(h) + "/"))
    return Path(os.path.expanduser(raw.strip()))


def show_manifest(manifest: dict) -> None:
    table = Table(show_header=False, box=None, padding=(0, 2))
    de = manifest["de"]
    table.add_row(t("import.created"), escape(str(manifest.get("created", "?"))))
    table.add_row(t("ui.desktop"), escape(f"{de.get('name', de.get('id'))} {de.get('version', '')}".strip()))
    table.add_row(t("ui.distro"), escape(str(manifest["distro"].get("pretty_name") or manifest["distro"].get("id"))))
    table.add_row(t("import.origin"), escape(f"{manifest.get('user', '?')}@{manifest.get('hostname', '?')}"))
    table.add_row(t("export.sum_files"), str(len(manifest["files"])))
    for key, entry in manifest["packages"].items():
        table.add_row(t(f"pkg.source.{key}", manager=entry.get("source", "")), str(entry.get("count", "?")))
    console.print(table)


def handle_packages(opened, env: Environment) -> None:
    actions = restore.package_actions(opened, env)
    if not actions:
        return
    console.print(f"\n[bold]{t('import.packages_title')}[/]")
    for act in actions:
        title = t(f"pkg.source.{act.key}", manager=act.packages.source)
        names = [p.name for p in act.packages.packages]
        console.print(f"[bold]{escape(title)}[/] ({len(names)})")
        if act.key == "aur":
            warn(t("import.aur_warning"))
        shown = " ".join(names[:SHOW_PACKAGES]) + (f" {t('import.more', n=len(names) - SHOW_PACKAGES)}" if len(names) > SHOW_PACKAGES else "")
        console.print(f"   [dim]{escape(shown)}[/]")
        if act.packages.invalid:
            warn(t("import.invalid_packages", n=len(act.packages.invalid)))
        if act.reason:
            warn(t(act.reason))
            continue
        if act.missing:
            warn(t("import.missing_packages", n=len(act.missing), names=" ".join(act.missing)))
        if not act.commands:
            continue
        for cmd in act.commands:
            shown = " ".join(cmd[:8]) + (" …" if len(cmd) > 8 else "")
            console.print(f"   [dim]$ {escape(shown)}[/]")
        if confirm(t("import.install_now"), default=True):
            failed = restore.run_commands(act.commands)  # no progress bar is active here
            if failed:
                error(t("import.install_failed", n=len(failed)))
            else:
                ok(t("import.installed"))


def show_plan(plan: restore.RestorePlan, mode: str) -> None:
    console.print(f"\n[bold]{t('import.summary')}[/]")
    console.print(t("import.sum_files", n=len(plan.items)))
    if plan.dconf:
        console.print(t("import.sum_dconf", n=len(plan.dconf)))
    if plan.extras:
        warn(t("import.sum_extras", names=", ".join(plan.extras)))
    if plan.autostart:
        warn(t("import.sum_autostart", names=", ".join(Path(a).name for a in plan.autostart)))
    if plan.ignored:
        warn(t("import.sum_ignored", n=len(plan.ignored)))
        for rel, reason in plan.ignored[:5]:
            console.print(f"   [dim]{escape(rel)} — {escape(t('reason.' + reason))}[/]")
    if plan.dconf and not dconf.can_load():
        warn(t("warn.dconf_unavailable"))
    info(t(f"mode.{mode}"))


def offer_logout(profile: Profile | None) -> None:
    cmd = logout_command(profile)
    if cmd is None:
        info(t("import.logout_manual"))
        return
    if confirm(t("import.logout_now"), default=False):
        subprocess.run(cmd, check=False)


def flow_import(env: Environment) -> None:
    h = home()
    path = pick_archive(h)
    if not path.is_file():
        error(t("import.not_found", path=str(path)))
        return
    try:
        with console.status(t("import.reading")):
            opened = read_archive(path, state_dir() / "tmp")
    except ArchiveError as exc:
        error(t("import.invalid", error=str(exc)))
        return
    try:
        _import_opened(opened, env, h)
    finally:
        opened.cleanup()


def _import_opened(opened, env: Environment, h: Path) -> None:
    manifest = opened.manifest
    show_manifest(manifest)
    profile, notices = restore.profile_from_manifest(manifest)
    notices += restore.compatibility(manifest, env, profile, h)
    for n in notices:
        notice(n)
    if any(n.key in ("warn.de_differs", "warn.de_not_installed") for n in notices) \
            and not confirm(t("import.confirm_de_differs"), default=False):
        raise Cancelled

    common = load_common()
    present = {f["category"] for f in manifest["files"]} | {d["category"] for d in manifest["dconf"]}
    cats = [c for c in restore.archive_categories(manifest, profile, common) if c.id in present]
    selected: set[str] = set()
    if cats:
        answer = ask(checkbox(t("import.categories"), [
            questionary.Choice(label(c.label) + (f"  ({t('export.extra')})" if c.id.startswith(EXTRA_PREFIX) else ""),
                               c.id, checked=True)
            for c in cats
        ], back=True))
        if answer == BACK:
            raise GoBack
        selected = set(answer)

    handle_packages(opened, env)  # D14: packages before configuration files

    plan = restore.build_plan(opened, profile, common, selected, h)
    if not plan.items and not plan.dconf:
        info(t("import.nothing"))
        return
    running = bool(profile) and is_running(profile.running_process)
    mode = choose_mode(profile, running)
    show_plan(plan, mode)
    if mode == "offline":
        info(t("import.offline_steps"))
        return

    if mode == "deferred":
        if pending.has_pending(h):
            if not confirm(t("import.replace_pending"), default=True):
                raise Cancelled
        if not confirm(t("import.confirm"), default=True):
            raise Cancelled
        pending.cancel_pending(h)
        pending.stage(opened, plan, h, profile.id)
        ok(t("import.staged"))
        info(t("import.slow_login"))
        offer_logout(profile)
        return

    if not confirm(t("import.confirm"), default=True):
        raise Cancelled
    with progress_bar() as bar:
        task = bar.add_task(t("import.restoring"), total=len(plan.items))
        backup, failed = restore.restore_immediate(
            opened, plan, h, profile.id if profile else "unknown",
            progress=lambda d, tot: bar.update(task, completed=d, total=tot))
    ok(t("import.done", n=len(plan.items), backup=str(backup.dir)))
    for path, err in failed:
        error(t("import.dconf_failed", path=path, error=err))
    if profile and not running:
        info(t("import.relogin"))


# --- undo (Task 31) ----------------------------------------------------------------------------------


def flow_undo(env: Environment) -> None:
    h = home()
    if pending.has_pending(h):
        data = pending.pending_info(h) or {}
        info(t("undo.pending_info", created=data.get("created", "?"), source=data.get("source", "?")))
        if confirm(t("undo.cancel_pending_confirm"), default=True):
            pending.cancel_pending(h)
            ok(t("undo.pending_cancelled"))
        return

    backup = restore.latest_backup(h)
    if backup is None:
        info(t("menu.no_backup"))
        return
    d = backup.data
    info(t("undo.backup_info", created=d.get("created", "?"), source=d.get("source", "?"),
           replaced=len(d.get("overwritten", [])), created_n=len(d.get("created_files", []))))
    if d.get("status") == "in_progress":
        warn(t("undo.was_interrupted"))
    if not confirm(t("undo.confirm"), default=True):
        raise Cancelled

    try:
        profile = load_profile(d.get("de", "")) if d.get("de") not in ("", "unknown") else None
    except ProfileError:
        profile = None
    mode = choose_mode(profile, bool(profile) and is_running(profile.running_process))
    if mode == "offline":
        info(t("import.offline_steps"))
        return
    if mode == "deferred":
        pending.stage_undo(backup, h)
        ok(t("undo.staged"))
        offer_logout(profile)
        return
    failed = restore.undo_backup(backup, h)
    if failed:
        error(t("undo.failed", n=len(failed)))
        for line in failed[:5]:
            console.print(f"   [dim]{escape(line)}[/]")
    else:
        ok(t("undo.done"))

