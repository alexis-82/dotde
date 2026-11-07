# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.1.0] - 2026-11-07

### Added
- A "Back" entry at the end of every list: during the export it returns to the previous step and keeps your choices, elsewhere it returns to the main menu.

### Changed
- Lists show a box next to each item: `[x]` for the items that are included, `[ ]` for the others, instead of coloured dots. The English instructions under the lists are gone.

## [1.0.0] - 2026-11-06

### Added
- Interactive terminal program (`dotde`) to export and import desktop environment settings, in English and Italian.
- Profiles for KDE Plasma, GNOME, XFCE, Hyprland and Sway, plus common settings (GTK, themes, icons, fonts, autostart, default applications); every category can be selected on export and on import.
- Optional export of other applications' folders from `~/.config`, with a warning for folders that may contain passwords or tokens.
- Package lists (pacman, apt, dnf, zypper, AUR, Flatpak with its remotes, Snap) saved in the archive and offered for reinstallation on the same distribution family; packages no longer available in the repositories are listed and skipped.
- A single `.tar.gz` archive with a manifest and checksums; paths of the old home folder are rewritten on import.
- Backup of the replaced files before every import, and "Undo last import" (the last 3 backups are kept, symbolic links included).
- KDE: when Plasma is running, the restore is applied at the next login, before the desktop starts. XFCE: restore from a text console. GNOME: settings restored through dconf.

### Security
- Archives are validated before anything is written (paths, links, checksums, package names, home folder), and keyrings, keys, tokens and caches are never exported.
