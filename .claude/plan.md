# Piano tecnico — DotDE v1.0.0 (rev. 3, dopo la seconda `/04-analyze`)

## Approccio

Si costruisce un pacchetto Python `dotde` (layout `src/`) con un nucleo **senza interfaccia** (rilevamento, profili, raccolta, archivio, pacchetti, ripristino) e uno strato **UI** separato (`questionary` + `rich`) che lo orchestra. Così il nucleo si testa con `pytest` senza simulare la tastiera.

Strategia **bottom-up per fasi utilizzabili**: prima rilevamento e profili, poi un export funzionante end-to-end, poi l'import immediato, poi i modi di ripristino differito/offline, infine annullamento e rifiniture.

I DE sono descritti da **profili TOML** (D5) caricati da un unico loader: il codice non contiene nomi di file specifici di un DE.

### Cosa cambia rispetto alla rev. 1 (findings di `analysis.md`)

| Finding | Modifica al piano |
|---|---|
| **B1** logout sovrascrive il ripristino | Tre **modi di ripristino** per profilo: `immediate`, `deferred` (KDE), `offline` (XFCE). Nuovo modulo `pending.py` e comando interno `dotde --apply-pending`. Task 27–29. |
| **M1** import scrive ovunque nelle radici | L'import costruisce un **piano di ripristino** che accetta solo percorsi del profilo o delle "app extra" del manifest; lista nera fissa. Task 11, 22. |
| **M2** iniezione opzioni con `sudo` | Validazione dei nomi pacchetto per sorgente + `--` prima dei nomi. Task 17, 26. |
| **M3** segreti e cache nelle app extra | Esclusioni globali per pattern + elenco app con segreti noti. Task 5, 12. |
| **M4** profilo dal DE rilevato | Profilo da `manifest.de.id`; le app extra sono pseudo-categorie nel manifest. Task 18, 21. |
| **M5** import interrotto | Giornale di backup scritto prima del primo file, scritture atomiche, Ctrl+C gestito. Task 11, 23. |
| **M6** remote Flatpak mancanti | Export dei remote, `remote-add --if-not-exists` all'import. Task 16, 26. |
| m1 categorie sovrapposte | Il loader rifiuta sovrapposizioni. Task 4, 7. |
| m2 `filter="data"` assente su 3.11.2 | Estrazione membro per membro con controllo manuale; filtro solo se disponibile. Task 20. |
| m3 ordine import / `sudo` con `rich` | Pacchetti prima delle config (D14); barre `rich` chiuse prima di comandi interattivi. Task 26, 30. |
| m4 5 DE non verificabili | Task di verifica in VM. Task 36. |

### Cosa cambia nella rev. 3 (seconda analisi)

| Finding | Modifica al piano |
|---|---|
| **A1** pseudo-categorie `extra:` non validate; archivi di terzi | Validazione dei nomi `extra:`; riepilogo pre-conferma con tutte le cartelle extra e i pacchetti AUR; avviso se utente/host del manifest differiscono; nuovo Non-Goal in spec. Task 18, 20, 22, 30. |
| m1 spazio disco, tmpfs, backup infiniti | Cartella di lavoro `~/.local/state/dotde/tmp/` (stesso filesystem), `pending/` ottenuta spostando i file, controllo spazio libero, solo gli ultimi 3 backup. Task 20, 23, 28. |
| m2 snap classic / flatpak misti | Snap classic un comando per pacchetto; flatpak raggruppati per (installazione, remote). Task 26. |
| m3 dettagli script differito | Valori quotati con `shlex.quote`, niente `exec`/`exit`, stdout e stderr su log; avviso "primo login più lento". Task 28, 30. |
| m4 ripristino differito fallito invisibile | Esito scritto su file e mostrato al successivo avvio; nuovo import con `pending/` esistente chiede conferma. Task 28, 30, 32. |
| m5 `dconf load` da TTY senza bus | `DBUS_SESSION_BUS_ADDRESS` impostata da `/run/user/$UID/bus` se manca, altrimenti avviso. Task 25. |

### Modi di ripristino (D6 rivista)

| Profilo | `restore_mode` | DE in esecuzione per l'utente? | Comportamento |
|---|---|---|---|
| KDE Plasma | `deferred` | sì (`plasmashell` attivo) | Prepara i file in `~/.local/state/dotde/pending/`, installa `~/.config/plasma-workspace/env/dotde-pending.sh`, propone il logout. Al login lo script lancia `dotde --apply-pending` (backup + scrittura) **prima** che Plasma parta, poi si cancella. |
| XFCE | `offline` | sì (`xfce4-session` attivo) | Installa solo i pacchetti; per i file chiede di fare logout e rilanciare DotDE da TTY. |
| GNOME, Hyprland, Sway | `immediate` | indifferente | Ripristino subito (dconf si applica in tempo reale; Hyprland/Sway non riscrivono le config). |
| qualsiasi | — | no (es. da TTY) | Ripristino immediato. |

"In esecuzione" si verifica cercando in `/proc` il processo del profilo (`running_process`) appartenente all'utente, non dalle variabili d'ambiente: così funziona anche da TTY.

Lo script in `plasma-workspace/env/` viene **sourced** da `/usr/lib/plasma-sourceenv.sh` nella **stessa shell** degli altri script `env/` dell'utente (verificato su Plasma 6.8.2), e il login aspetta che finisca. Quindi: POSIX `sh`, nessun `exit` né `exec`, valori quotati con `shlex.quote`, `dotde` lanciato come processo separato con stdout e stderr su `~/.local/state/dotde/apply.log`, cancellazione con percorso esplicito.

### Formato del profilo TOML

```toml
# Le chiavi di primo livello (exclude, sensitive_apps) vanno PRIMA di ogni tabella:
# in TOML quelle scritte dopo un [[category]] appartengono alla categoria.
exclude = ["~/.local/share/kwalletd/"]    # esclusioni specifiche del DE

[meta]
id = "kde"                                # coincide con l'id restituito da detect.py
name = "KDE Plasma"
version_cmd = ["plasmashell", "--version"]
running_process = "plasmashell"
restore_mode = "deferred"                 # immediate | deferred | offline
logout_cmd = ["qdbus6", "org.kde.Shutdown", "/Shutdown", "logout"]

[[category]]
id = "appearance"
label = { en = "Appearance", it = "Aspetto" }
paths = ["~/.config/kdeglobals", "~/.local/share/color-schemes/"]
dconf = []                                # usato solo da GNOME
```

### Formato dell'archivio

```
dotde-<de>-<host>-<AAAAMMGG-HHMM>.tar.gz
├── manifest.json        # versione dotde, data, distro {id, id_like, family}, de {id, version},
│                        # utente, home, categorie scelte (incluse pseudo-categorie "extra:<cartella>"),
│                        # file + sha256 + categoria di appartenenza
├── files/               # percorsi relativi alla home: files/.config/kwinrc, files/.icons/…
├── dconf/<categoria>.ini
└── packages/
    ├── native.txt       # pacman/apt/dnf/zypper
    ├── aur.txt
    ├── flatpak.txt      # id, remote, installation (user/system)
    ├── flatpak-remotes.txt  # nome, url, installation
    └── snap.txt         # nome, flag classic
```

### Regole per i nomi `extra:` (A1)

Un solo componente di percorso direttamente sotto `~/.config`, regex `^[A-Za-z0-9._-]+$`, diverso da `.` e `..`, non coperto da un profilo, non in lista nera. Un manifest con un nome non valido viene rifiutato.

### Lista nera fissa (mai scritta all'import, mai esportata)

`~/.local/bin/`, `~/.local/state/dotde/`, `~/.config/plasma-workspace/env/` (scritta solo da DotDE stesso per lo script differito), `~/.config/systemd/`.

## File / moduli / componenti coinvolti

- [ ] `pyproject.toml` — nuovo: metadati, Python ≥ 3.11, dipendenze `questionary`, `rich`; entry point `dotde = dotde.cli:main`; versione letta da `version`.
- [ ] `main.py` — oggi vuoto: diventa un launcher per lo sviluppo che chiama `dotde.cli.main()`.
- [ ] `src/dotde/__init__.py`, `__main__.py` — pacchetto e `python -m dotde`.
- [ ] `src/dotde/i18n.py` + `src/dotde/locales/{en,it}.json` — `t(key, **kw)`, lingua da `LC_ALL`/`LANG`, fallback inglese (D9).
- [ ] `src/dotde/detect.py` — distro, famiglia distro, DE, versione DE, tipo sessione.
- [ ] `src/dotde/profiles.py` + `src/dotde/profiles/{common,kde,gnome,xfce,hyprland,sway}.toml` — schema, validazione (radici, lista nera, sovrapposizioni), caricamento.
- [ ] `src/dotde/paths.py` — radici consentite, lista nera, contenimento, esclusioni glob, `is_text_file()`, `rewrite_home()`, `atomic_write()`.
- [ ] `src/dotde/collect.py` — file concreti da categorie + app extra; candidate extra con flag "contiene segreti".
- [ ] `src/dotde/dconf.py` — dump e load per percorso.
- [ ] `src/dotde/packages.py` — adattatori (pacman, apt, dnf, zypper, aur, flatpak, snap), validazione nomi, comandi di installazione.
- [ ] `src/dotde/archive.py` — scrittura e lettura/validazione sicura.
- [ ] `src/dotde/restore.py` — piano di ripristino, compatibilità, giornale di backup, scrittura, riscrittura percorsi, dconf load, annullamento.
- [ ] `src/dotde/pending.py` — preparazione del ripristino differito, script `env/`, `apply_pending()` non interattivo, annullamento del ripristino in attesa.
- [ ] `src/dotde/session.py` — DE in esecuzione (`/proc`), logout.
- [ ] `src/dotde/ui.py` — schermate e flussi.
- [ ] `src/dotde/cli.py` — `main()`: controllo versione Python, gestione Ctrl+C, flag interno `--apply-pending`, avvio UI.
- [ ] `tests/` — `pytest` con home finta (`tmp_path` + `monkeypatch` di `HOME`) e comandi esterni simulati.

## Ordine di implementazione

1. **Fondamenta** (Task 1–3).
2. **Profili** (Task 4–10).
3. **Raccolta** (Task 11–13).
4. **Pacchetti in lettura** (Task 14–17).
5. **Export end-to-end** (Task 18–19) → **Traguardo 1:** archivio reale.
6. **Import immediato** (Task 20–26).
7. **Modi di ripristino + UI import** (Task 27–30) → **Traguardo 2:** ciclo export → import completo, anche su KDE con sessione attiva.
8. **Annullamento, menu, logout, errori** (Task 31–34).
9. **Verifica finale** (Task 35–36).

## Rischi e dipendenze

- [ ] **Path traversal / archivi manipolati.** Mitigazione: estrazione membro per membro con controllo manuale (difesa principale), `filter="data"` in aggiunta se disponibile; piano di ripristino limitato ai percorsi del profilo (D13); lista nera fissa.
- [ ] **Script differito che rompe l'ambiente della sessione KDE.** Un errore di sintassi o un `exit` non blocca il login ma interrompe la shell condivisa: gli altri script `env/` dell'utente non vengono caricati e le loro variabili si perdono. Mitigazione: script minimale e fisso (nessun dato dall'archivio interpolato, percorsi quotati), test con `sh -n` e con percorsi contenenti spazi e apostrofi, comando con `|| true`, output su file di log.
- [ ] **Login più lento** durante l'applicazione differita. Mitigazione: i file sono già pronti in `pending/` (solo spostamenti/copie locali); il riepilogo dell'import avvisa.
- [ ] **`dotde` non trovato al login** (installato con pipx in `~/.local/bin`, che a quel punto può non essere nel `PATH`). Mitigazione: lo script usa il percorso assoluto dell'eseguibile rilevato al momento della preparazione (`sys.executable -m dotde`).
- [ ] **Comandi pacchetti diversi tra versioni** (`dnf` 4/5, `zypper`). Mitigazione: adattatori con test sull'output reale; zypper usa `/var/lib/zypp/AutoInstalled`.
- [ ] **Pacchetti spariti o rinominati.** Mitigazione: `--needed`, riepilogo dei falliti invece di fallire tutto.
- [ ] **AUR senza helper / Snap classic.** Mitigazione: solo lista + avviso; flag `--classic` dal campo notes.
- [ ] **Riscrittura percorsi su file binari.** Mitigazione: solo file UTF-8 senza NUL; backup.
- [ ] **Profili incompleti.** Mitigazione: validazione schema; verifica su KDE (Task 35) e in VM (Task 36).
- [ ] **Dimensione e spazio** (icone, cache, `/tmp` in RAM su CachyOS). Mitigazione: esclusioni per pattern (M3), stima prima della conferma, cartella di lavoro su disco in `~/.local/state/dotde/tmp/`, controllo spazio libero, massimo 3 backup conservati.
- [ ] **Archivi di terzi** che contengono config eseguibili o pacchetti AUR non fidati. Mitigazione parziale e dichiarata (Non-Goal): riepilogo completo prima della conferma, avviso su utente/host diversi.
- [ ] Dipendenze: `questionary`, `rich`; comandi opzionali `dconf`, `flatpak`, `snap`, `paru`/`yay`, `qdbus6`, `loginctl`.

## Deviazioni emerse in implementazione (`/05-implement`)

| Punto del piano | Cosa è stato fatto | Perché |
|---|---|---|
| Estrazione con `filter="data"` se disponibile | Nessun `extractall`: ogni membro viene validato e copiato con `extractfile()` in un file aperto con `"xb"` | Non dipende dalla versione di Python (3.11.2 compreso) e non può seguire link o sovrascrivere nulla: il filtro diventa superfluo. |
| `meta.detect` nei profili | Rimosso: l'id del profilo coincide con quello restituito da `detect.py` | Evita di mantenere gli alias in due posti. |
| Percorsi "opzionali" nei profili (Task 6) | Tutti i percorsi sono opzionali, quelli mancanti vengono saltati | KDE crea molti file solo dopo aver cambiato l'impostazione relativa (9 su 40 assenti sul sistema dello sviluppatore). |
| Esclusioni dei segreti in `exclude` | Nuova chiave `secret_patterns` in `common.toml`, separata da `exclude` | Le cache non devono far marcare una cartella come "sensibile"; i segreti sì. |
| Chiavi sconosciute nei TOML | Il loader le rifiuta | In TOML le chiavi scritte dopo un `[[category]]` finiscono dentro la categoria: l'errore era successo davvero con `exclude`. |
| zypper: `/var/lib/zypp/AutoInstalled` | Righe `i+` di `zypper search --installed-only` | `i+` indica già i pacchetti installati su richiesta dell'utente. |
| `--` prima dei nomi pacchetto | Usato per pacman, paru/yay, dnf, flatpak, snap; non per `apt-get` e `zypper` | Non è certo che questi due lo supportino: la validazione vieta comunque nomi che iniziano con `-`. |
| Versione del DE | Letta solo se c'è un display (`WAYLAND_DISPLAY`/`DISPLAY`) | `plasmashell --version` va in crash senza display e resta appeso con `QT_QPA_PLATFORM=offscreen`. Da TTY si salta solo l'avviso sulla versione maggiore. |
| Annulla in modo differito (Task 31) | `pending.json` supporta anche una lista `delete` e `undo_of` | Serve per eliminare al login i file creati dall'import. |
| Undo dconf | `dconf reset -f` prima di ricaricare il backup | `dconf load` non toglie le chiavi aggiunte dall'import. |
| Undo dei file creati | Rimuove anche le cartelle rimaste vuote, mai la radice | Emerso nella prova guidata (`~/.config/fish/completions` vuota). |

## Verifica di allineamento con la spec

- [x] G1 → Task 3 · G2 → Task 19, 30, 32 · G3 → Task 11–13, 18 · G4 → Task 14–17 · G5 → Task 18 · G6 → Task 20–30 · G7 → Task 23, 31 · G8 → Task 12, 19, 30 · G9 → Task 26.
- [x] Non-Goal "archivi di terzi" (rev. 3) rispettato: nessun task promette di renderli sicuri, i Task 22 e 30 si limitano a mostrare e avvisare.
- [x] Criteri aggiunti dopo l'analisi: ripristino differito KDE → Task 28; rifiuto XFCE → Task 29; file fuori profilo ignorati → Task 22; nomi pacchetto non validi → Task 17.
- [x] Nessun task salva o scrive fuori dalle quattro radici (controllo centralizzato in `paths.py`); l'unica scrittura in `~/.config/plasma-workspace/env/` è lo script fisso di DotDE.
- [x] Nessuna GUI, nessun cloud, nessuna cifratura, nessuna conversione tra DE o traduzione di nomi pacchetti; solo i cinque DE previsti.
