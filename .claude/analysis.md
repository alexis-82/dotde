# Analisi critica — DotDE v1.0.0 (rev. 2)

Seconda analisi, su `spec.md`, `plan.md` e `tasks.md` aggiornati dopo la prima. Il codice esistente è ancora vuoto, quindi non ci sono regressioni possibili.

**Totale: 0 blocker · 1 major · 5 minor.** Prestazioni: un solo punto, sotto m1.

## Stato dei finding della rev. 1

| Finding | Stato | Dove è coperto |
|---|---|---|
| B1 logout sovrascrive il ripristino | ✅ risolto | D6 rivista, Task 27–29. Meccanismo verificato sul sistema (vedi sotto). |
| M1 import scrive ovunque nelle radici | ⚠ risolto in parte | Task 11, 22. Resta un varco: vedi **A1**. |
| M2 iniezione opzioni con `sudo` | ✅ risolto | Task 17, 26 |
| M3 segreti e cache nelle app extra | ✅ risolto | Task 5, 12 |
| M4 profilo dal DE rilevato | ✅ risolto | Task 21 |
| M5 import interrotto | ✅ risolto | Task 11, 23, 24 |
| M6 remote Flatpak | ✅ risolto | Task 16, 26 |
| m1–m4 | ✅ risolti | Task 4, 7, 20, 26, 30, 36 |

### Verifica del meccanismo differito (B1)

Su Plasma 6.8.2 (sistema dello sviluppatore) `startplasma-wayland` cerca `*.sh` in `~/.config/plasma-workspace/env/` (la cartella esiste già, vuota) e li passa a `/usr/lib/plasma-sourceenv.sh`, che fa:

```sh
for i in $@; do . $i >/dev/null; done
env -0 2>/dev/null || genv -0
```

Questo conferma che il meccanismo funziona e precisa tre dettagli (vedi **m3**): lo stdout dello script è già scartato, gli script girano in **una sola** shell condivisa, e il login aspetta che finiscano.

---

## Major

### A1 — Le pseudo-categorie `extra:` del manifest riaprono il varco di M1
- **Dove:** `tasks.md` Task 18 e Task 22; `plan.md` "Formato dell'archivio"; D13 in `spec.md`.
- **Scenario 1 (nome non validato):** un manifest dichiara `extra:../.local/bin` o `extra:plasma-workspace` → il Task 22 accetta tutto ciò che corrisponde a una pseudo-categoria `extra:` → l'unica difesa è la lista nera, e qualunque cartella non in lista nera diventa scrivibile.
- **Scenario 2 (codice eseguito tramite config legittime):** anche con nomi validi, un archivio preso da terzi (es. "il mio rice" su un forum) può dichiarare `extra:fish` con `config.fish` che esegue comandi a ogni apertura del terminale, oppure elencare in `aur.txt` un pacchetto AUR malevolo che `paru` compila. È un limite intrinseco del ripristinare config di app, ma oggi il piano lo presenta come risolto da M1 e il riepilogo prima della conferma mostra solo gli autostart.
- **Correzione suggerita:**
  1. Validare i nomi `extra:`: un solo componente di percorso direttamente sotto `~/.config`, regex `^[A-Za-z0-9._-]+$`, diverso da `.` e `..`, non coperto da un profilo e non in lista nera.
  2. Nel riepilogo prima della conferma elencare **tutte** le cartelle extra e i pacchetti AUR in arrivo, non solo gli autostart.
  3. Avviso esplicito se utente e host del manifest non coincidono con quelli attuali (indizio di un archivio di terzi).
  4. Aggiungere alla spec un Non-Goal: "**NON** garantire la sicurezza dell'import di archivi creati da altri: DotDE è pensato per i propri backup".

---

## Minor

### m1 — Spazio su disco: estrazione in `/tmp` (tmpfs), tre copie dei file, backup mai cancellati
- **Dove:** Task 20 ("cartella temporanea"), Task 23, Task 28.
- **Scenario:** su CachyOS `/tmp` è un tmpfs (7,7 GB su questo sistema, cioè RAM). Un import differito passa i file da `/tmp` a `pending/` e poi al backup: sono tre copie. Con un archivio contenente qualche GB di temi e icone l'estrazione può fallire per spazio, o consumare RAM. In più ogni import crea un `backup-<data>/` che nessuno cancella mai.
- **Nota:** su questo sistema temi e icone utente pesano poco (`~/.icons` e `~/.themes` non esistono, `~/.local/share/icons` è vuota), quindi il problema riguarda gli utenti con molti temi.
- **Correzione:** estrarre in `~/.local/state/dotde/tmp/` (stesso filesystem della destinazione, così `pending/` si ottiene **spostando** i file invece di copiarli), controllare lo spazio libero prima di estrarre, tenere solo gli ultimi 3 backup.

### m2 — Comandi Snap e Flatpak non raggruppati correttamente
- **Dove:** Task 26.
- **Scenario:** `sudo snap install --classic code nvim` fallisce ("a single snap name is needed to specify mode or channel flags"): con `--classic` serve un comando per pacchetto. Analogamente `flatpak install` con app di installazioni diverse (utente e sistema) o di remote diversi nella stessa chiamata installa nel posto sbagliato o fallisce.
- **Correzione:** snap normali in un solo comando, snap classic uno alla volta; flatpak raggruppati per (installazione `--user`/`--system`, remote), con `--noninteractive`.

### m3 — Dettagli dello script differito da precisare
- **Dove:** Task 28; rischio "Script differito che rompe il login KDE" in `plan.md`.
- **Scenario 1:** gli script di `env/` girano tutti nella **stessa** shell (`for i in $@; do . $i; done`). Un `exit` o un errore di sintassi nel nostro script non blocca il login, ma interrompe quella shell: gli script successivi non vengono caricati e `env -0` non gira, quindi **si perdono le variabili d'ambiente di tutti gli altri script dell'utente** per quella sessione. Il piano descrive il rischio in modo leggermente diverso: la mitigazione (niente `exit`, `sh -n`) resta giusta.
- **Scenario 2:** il percorso di `sys.executable` scritto nello script contiene uno spazio o un apostrofo (es. `/home/d'angelo/...`) → errore di sintassi → scenario 1.
- **Scenario 3:** il login aspetta la fine dello script. Con molti file da applicare il login si allunga, senza alcun messaggio sullo schermo.
- **Correzione:** valori nello script quotati con `shlex.quote`; lo script deve *eseguire* `dotde` come processo separato e non sostituire la shell (`exec`); log anche dello stderr (`>>"$LOG" 2>&1`). Il riepilogo dell'import deve dire che il primo login potrà richiedere qualche secondo in più.

### m4 — Un ripristino differito fallito resta invisibile
- **Dove:** Task 28, Task 32.
- **Scenario:** `apply_pending()` fallisce al login (es. disco pieno) → lo script si cancella, l'errore finisce in `apply.log`, Plasma parte con le config vecchie. L'utente non lo sa: pensa che il ripristino abbia funzionato a metà. Inoltre, se l'utente lancia due import prima di fare logout, non è definito cosa succede al primo `pending/`.
- **Correzione:** `apply_pending()` scrive l'esito in `pending.json`/`apply.log`; al successivo avvio di DotDE, se l'ultimo esito è un errore, l'intestazione lo mostra con il percorso del log. Un nuovo import con un `pending/` esistente chiede se sostituirlo.

### m5 — `dconf load` da TTY può fallire senza bus di sessione
- **Dove:** Task 25, Task 29 (il ripristino da TTY è uno dei percorsi previsti).
- **Scenario:** import GNOME da TTY → `DBUS_SESSION_BUS_ADDRESS` non è impostata → `dconf load` non riesce a contattare `dconf-service` ed esce con errore → le impostazioni GNOME non vengono ripristinate, mentre i file sì.
- **Correzione:** se la variabile manca e `/run/user/$UID/bus` esiste, impostarla per il sottoprocesso `dconf`; altrimenti avvisare prima della conferma che le impostazioni dconf non si possono ripristinare da qui.

---

## Esito

**Nessun blocker.** A1 è l'unico major e si risolve con poche righe in Task 18 e Task 22, più un Non-Goal nella spec. I minor sono precisazioni di task già esistenti.

Due strade possibili:
- aggiornare piano e task con `/03-plan-tasks` (passaggio breve, nessuna decisione architetturale da prendere), poi `/05-implement`;
- passare subito a `/05-implement`, integrando A1 e i minor nei task corrispondenti man mano che si arriva lì.
