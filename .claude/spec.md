# Specifica — DotDE v1.0.0

## Obiettivo

Permettere a un utente Linux di esportare le configurazioni del proprio Desktop Environment (e la lista dei pacchetti installati) in un unico archivio, e di ripristinarle su un sistema appena reinstallato, tramite un programma interattivo da terminale.

## Goals (cosa DEVE fare)

- [ ] **G1 — Rilevamento ambiente:** all'avvio rileva e mostra distribuzione (da `/etc/os-release`, con `ID` e `ID_LIKE`), Desktop Environment (da `XDG_CURRENT_DESKTOP`, con fallback) e tipo di sessione (wayland/x11).
- [ ] **G2 — Interfaccia interattiva:** il programma si usa tramite menu e domande nel terminale (scegli export/import, conferma, seleziona voci), senza dover ricordare comandi o flag.
- [ ] **G3 — Export config:** raccoglie i file di configurazione del DE rilevato presenti in `~/.config` e `~/.local`, più temi e icone utente in `~/.themes` e `~/.icons`, e li salva in un archivio `.tar.gz`.
- [ ] **G4 — Export lista pacchetti:** salva nell'archivio la lista dei pacchetti installati esplicitamente dall'utente, usando il gestore pacchetti della distro rilevata (pacman, apt, dnf, zypper), più AUR (su Arch), Flatpak (con i relativi remote) e Snap se presenti.
- [ ] **G5 — Manifest:** l'archivio contiene un `manifest.json` con: versione DotDE, data, distro, DE e versione del DE, nome utente originale, elenco dei file salvati.
- [ ] **G6 — Import config:** dato un archivio, mostra il contenuto del manifest, avvisa se DE o distro differiscono dal sistema attuale, e ripristina i file in `~/.config`, `~/.local`, `~/.themes` e `~/.icons` previa conferma.
- [ ] **G7 — Sicurezza del ripristino:** prima di sovrascrivere, salva una copia dei file esistenti in `~/.local/state/dotde/backup-<data>/`; dal menu si può annullare l'ultimo import.
- [ ] **G8 — Selezione:** nell'export e nell'import l'utente sceglie con checkbox le categorie del profilo DE (tutte selezionate di default) e le cartelle di app extra da `~/.config` da includere.
- [ ] **G9 — Reinstallazione pacchetti:** all'import, se la famiglia di distro coincide, mostra il comando di installazione e lo esegue con `sudo` previa conferma; altrimenti mostra solo la lista con un avviso.

## Non-Goals (cosa NON deve fare) — scope hard

- [ ] **NON** salvare file fuori da `~/.config`, `~/.local`, `~/.themes` e `~/.icons` (niente `~/.bashrc`, `~/.zshrc`, `~/.ssh`, `/etc`, ecc.).
- [ ] **NON** offrire un'interfaccia grafica (Qt/GTK): solo terminale.
- [ ] **NON** convertire configurazioni tra DE diversi (es. da KDE a GNOME) né tra versioni maggiori dello stesso DE (es. Plasma 5 → 6): al massimo avvisa.
- [ ] **NON** salvare dati sensibili o cache: esclusi portachiavi (kwallet, gnome-keyring), profili browser, cache e thumbnail.
- [ ] **NON** sincronizzare su cloud, né fare backup programmati, incrementali o versionati: un export = un archivio.
- [ ] **NON** cifrare l'archivio in questa versione.
- [ ] **NON** gestire più utenti o richiedere privilegi di root per l'export.
- [ ] **NON** supportare nella v1 DE diversi da KDE Plasma, GNOME, XFCE, Hyprland e Sway (Cinnamon, MATE, Budgie, i3 ecc. arriveranno dopo come nuovi profili).
- [ ] **NON** tradurre i nomi dei pacchetti tra distro diverse (es. pacman → apt).
- [ ] **NON** garantire la sicurezza dell'import di archivi creati da altri: DotDE è pensato per i propri backup. Un archivio di terzi può contenere config che eseguono comandi (es. `config.fish`, autostart) o pacchetti AUR non fidati; DotDE si limita a mostrarli e avvisare.

## Utenti / consumatori

Utente desktop Linux, anche non esperto, che sta per formattare o ha appena reinstallato il sistema e vuole ritrovare il proprio ambiente com'era. Usa il programma raramente (prima e dopo una reinstallazione), quindi l'interfaccia deve guidarlo passo per passo.

## Interfaccia

Programma da terminale interattivo, avviato con un unico comando (es. `dotde`):

1. Schermata iniziale con l'ambiente rilevato (distro, DE, sessione).
2. Menu principale: **Esporta** / **Importa** / **Annulla ultimo import** (o **Annulla ripristino in attesa**) / **Esci**.
3. **Esporta:** mostra a checkbox le categorie del profilo DE e le cartelle di app extra, più le sorgenti pacchetti; chiede conferma e dove salvare l'archivio, poi mostra un riepilogo finale.
4. **Importa:** chiede il percorso dell'archivio, mostra il manifest e gli eventuali avvisi di incompatibilità, fa scegliere le categorie da ripristinare, propone **prima** la reinstallazione dei pacchetti, poi chiede conferma e ripristina i file (riscrivendo i percorsi `/home/<vecchioutente>`) e mostra un riepilogo (file ripristinati, percorso del backup). Il modo di ripristino dipende dal DE (vedi D6): immediato, differito al prossimo login (KDE con sessione attiva, poi propone il logout) oppure rifiutato con invito a rilanciare da TTY (XFCE con sessione attiva).
5. **Annulla ultimo import:** ripristina i file dal backup più recente in `~/.local/state/dotde/`.

Output: un file `dotde-<de>-<host>-<data>.tar.gz` contenente le config, la lista pacchetti e `manifest.json`.

## Criteri di accettazione

- [ ] Su un sistema KDE Plasma, il programma rileva correttamente distro e DE e li mostra all'avvio.
- [ ] L'export produce un `.tar.gz` che contiene `manifest.json`, la lista pacchetti e i file di config attesi per il DE, e nessun file fuori da `~/.config`, `~/.local`, `~/.themes` e `~/.icons`.
- [ ] L'archivio non contiene file di kwallet, gnome-keyring, profili browser o cartelle di cache.
- [ ] Importando l'archivio su un utente pulito con lo stesso DE, dopo il riavvio della sessione l'aspetto e le impostazioni del DE corrispondono a quelli di partenza.
- [ ] Se l'archivio è di un DE diverso da quello attuale, l'import mostra un avviso e chiede conferma esplicita prima di procedere.
- [ ] Prima dell'import, i file esistenti che verrebbero sovrascritti vengono copiati in una cartella di backup, e il riepilogo ne indica il percorso.
- [ ] Se l'utente annulla in qualunque momento **prima della conferma finale**, nessun file viene scritto o modificato; se l'import si interrompe dopo, "Annulla ultimo import" riporta i file allo stato precedente.
- [ ] Su KDE con sessione attiva, l'import non scrive le config subito: le applica al login successivo, prima dell'avvio di Plasma, e dopo il login le impostazioni sono quelle dell'archivio.
- [ ] Su XFCE con sessione attiva, l'import non scrive file di config e chiede di rilanciare DotDE da TTY.
- [ ] Un file dell'archivio che non appartiene a una categoria del profilo né a una cartella "app extra" del manifest non viene scritto e compare nel riepilogo come ignorato.
- [ ] Un nome di pacchetto non valido (es. che inizia con `-`) non viene mai passato al gestore pacchetti.
- [ ] Il programma riconosce e gestisce KDE Plasma, GNOME, XFCE, Hyprland e Sway.
- [ ] Se l'archivio proviene da un utente con home diversa, nei file di testo ripristinati non resta nessuna occorrenza del vecchio percorso `/home/<vecchioutente>`.
- [ ] "Annulla ultimo import" riporta i file sovrascritti allo stato precedente all'import.
- [ ] Con `LANG=it_*` i messaggi sono in italiano, altrimenti in inglese.

## Vincoli tecnici

- Linguaggio: Python 3.11+ (serve `tomllib` della libreria standard).
- Dipendenze esterne: solo `questionary` e `rich`; distribuzione consigliata via `pipx`.
- Ambiente: Linux, utente normale (no root per l'export).
- Distro target: famiglie Arch, Debian/Ubuntu, Fedora, openSUSE (riconosciute tramite `ID_LIKE`).
- Sicurezza: nessun dato sensibile nell'archivio; all'import i file vanno scritti solo dentro `~/.config`, `~/.local`, `~/.themes` e `~/.icons` (nessun percorso dell'archivio può uscire da lì).
- Nota: per GNOME/Cinnamon/MATE le impostazioni stanno nel database dconf, che si trova in `~/.config/dconf/user`, quindi rientra nello scope `~/.config`.

## Decisioni prese

| # | Decisione | Alternative valutate | Motivazione |
|---|---|---|---|
| D1 | **Raccolta = profilo DE + app extra scelte dall'utente** | `.config`/`.local` interi; solo profilo DE | Archivio piccolo (MB, non GB), niente dati estranei, ma l'utente può aggiungere le config delle sue app. |
| D2 | **UI con `questionary` + `rich`** | Solo stdlib; `textual` | Menu a frecce e checkbox adatti a un utente non esperto, con 2 sole dipendenze. `textual` costa troppo codice per un tool usato raramente. |
| D3 | **Pacchetti: proposta + installazione con `sudo` se stessa famiglia di distro** | Solo lista | Comodo nel caso tipico (reinstallo la stessa distro), sicuro nel caso diverso (solo lista + avviso). |
| D4 | **DE v1: KDE Plasma, GNOME, XFCE, Hyprland, Sway** | Solo KDE + GNOME | Scelta dell'utente; sostenibile perché i profili sono dati (D5). |
| D5 | **Profili DE in file TOML** (`profiles/<de>.toml`, con categorie) | Dizionari Python nel codice | Con 5 DE conviene separare i dati dal codice; `tomllib` è nella stdlib. |
| D6 | **Modo di ripristino per DE** (rivisto dopo `/04-analyze`, B1): KDE con sessione attiva → ripristino **differito** tramite script una tantum in `~/.config/plasma-workspace/env/`, eseguito al login prima di Plasma, poi logout proposto; XFCE con sessione attiva → rifiuto e invito a usare un TTY; GNOME, Hyprland, Sway e qualsiasi DE non in esecuzione → immediato | Avviso + logout; solo da TTY; fermare i processi | Al logout Plasma e XFCE salvano lo stato in memoria sopra i file ripristinati, quindi il logout dopo l'import annullava il ripristino. Fermare i processi non funziona con kwin su Wayland. |
| D7 | **Riscrittura automatica di `/home/<vecchioutente>`** nei soli file di testo | Chiedere conferma; non riscrivere | Senza riscrittura molti percorsi (sfondi, preferiti) risultano rotti; il backup (D10) rende l'operazione reversibile. |
| D8 | **Sorgenti pacchetti: distro + AUR + Flatpak + Snap** | Solo gestore della distro | AUR è centrale su Arch/CachyOS, Flatpak e Snap contengono spesso molte app desktop. |
| D9 | **Messaggi in inglese e italiano** in base a `LANG`, fallback inglese | Solo italiano; solo inglese | Raggiunge più utenti con un piccolo file di traduzioni. |
| D10 | **Python 3.11+** | 3.12+ | `tomllib` incluso; copre Debian 12, Ubuntu 24.04, Fedora, Arch. |
| D11 | **Selezione per categorie a checkbox**, tutte attive di default, in export e import | Profilo tutto o niente | Permette ripristini parziali (es. solo scorciatoie) senza complicare il caso base. |
| D12 | **Backup in `~/.local/state/dotde/backup-<data>/`** + voce di menu "Annulla ultimo import" | Archivio di backup accanto all'import | Percorso standard XDG; l'annullamento diventa un'azione del programma, non un'operazione manuale. |
| D13 | **All'import il profilo si prende dal manifest** e si scrivono solo percorsi delle sue categorie o delle cartelle "app extra" dichiarate nel manifest | Profilo dal DE rilevato; tutto ciò che sta nelle radici | Da TTY il DE non è rilevabile; un archivio modificato non deve poter scrivere in `~/.local/bin/` o simili (`/04-analyze`, M1/M4). |
| D14 | **Pacchetti prima delle config** all'import | Config prima | Temi e widget installati come pacchetti devono esistere quando il DE legge la config (`/04-analyze`, m3). |

## Ambiguità aperte

- [?risolvere-dopo: dipende dai profili TOML in fase di piano] Elenco preciso dei file e delle categorie per ciascun DE, e lista delle esclusioni comuni (cache, segreti).
- [?risolvere-dopo: dipende dal comportamento reale di dconf] Per GNOME, se copiare il file binario `~/.config/dconf/user` o usare `dconf dump`/`dconf load` limitato alle chiavi del DE.
