<div align="center">

# DotDE

**Save your Linux desktop settings and get them back after reinstalling the system**<br>
*Salva le impostazioni del tuo desktop Linux e ritrovale dopo aver reinstallato il sistema*

[![Version](https://img.shields.io/badge/version-1.1.0-blue?style=plastic)](CHANGELOG.md)&nbsp;&nbsp;&nbsp;[![Python](https://img.shields.io/badge/Python-3776AB?style=plastic&logo=python&logoColor=white)](#)&nbsp;&nbsp;&nbsp;[![Platform](https://img.shields.io/badge/platform-Linux-lightgrey?style=plastic)](#)

🇬🇧 [English](#en)&nbsp;&nbsp;·&nbsp;&nbsp;🇮🇹 [Italiano](#it)

</div>

---

<a id="en"></a>
<a id="contents"></a>
## 📑 Contents

- [✨ What it is](#what-it-is)
- [🚀 Installation](#installation)
- [🧭 How to use](#how-to-use)
- [🛟 Troubleshooting](#troubleshooting)
- [📄 License](#license)

---

<a id="what-it-is"></a>
## ✨ What it is

DotDE is a terminal program that saves the look and the settings of your desktop in a single file, and puts them back when you need them, for example after formatting your computer.

It saves:

- appearance (theme, colours, icons, fonts, wallpaper), panels and widgets, window behaviour, keyboard shortcuts, mouse and keyboard settings;
- if you want, the settings of other programs you use;
- the list of programs you installed, so it can offer to install them again.

It works with KDE Plasma, GNOME, XFCE, Hyprland and Sway, on Arch, Debian, Ubuntu, Fedora, openSUSE and the distributions based on them. It speaks English and Italian.

It never saves passwords, keys or browser data. Before changing anything it keeps a copy of your current settings, so you can always go back.

<a id="installation"></a>
## 🚀 Installation

You need Linux with Python 3.11 or newer, which recent distributions already include.

1. Open the Terminal and install **pipx** (the tool that installs DotDE) and **git**, with the command for your system:

   ```bash
   sudo pacman -S python-pipx git    # Arch, CachyOS, Manjaro
   sudo apt install pipx git         # Debian, Ubuntu, Mint
   sudo dnf install pipx git         # Fedora
   ```

   On other distributions, look for *pipx* and *git* in your software manager.

2. Then paste these two commands:

   ```bash
   pipx ensurepath
   pipx install git+https://github.com/alexis-82/dotde
   ```

3. Close the Terminal and open it again.

<a id="how-to-use"></a>
## 🧭 How to use

Open the Terminal and type `dotde`. A menu appears: move with the arrow keys and press Enter to choose. In the lists with boxes, press Space to add or remove the `[x]`: only the items with `[x]` are used. Choose **← Back** at the end of a list to go back.

**Before formatting**

1. Choose **Export my configuration**.
2. Choose what to save (everything is already selected) and where to put the file.
3. Copy the file you get (`dotde-….tar.gz`) to a USB stick or to the cloud.

**After reinstalling**

1. Install DotDE again and copy the file back to your computer.
2. Type `dotde`, choose **Import a configuration** and pick the file.
3. DotDE first offers to reinstall your programs, then shows what it will change and asks you to confirm.
4. On KDE Plasma the settings are applied the next time you log in: DotDE offers to log you out. On XFCE it asks you to log out and run it from a text console (Ctrl+Alt+F3).

Changed your mind? Choose **Undo last import** to get your previous settings back.

Only import files you created yourself: a file made by someone else could contain settings that start programs.

<a id="troubleshooting"></a>
## 🛟 Troubleshooting

- **"The restore at login failed"**: DotDE tells you at the next start, together with the file that has the details. Import the file again, or choose **Undo last import**.
- **Some programs are skipped**: they no longer exist in your distribution. Install a replacement yourself.
- **Programs are not installed automatically**: the file comes from a different family of distributions (for example from Arch to Ubuntu). DotDE shows you the list, so you can install them yourself.
- **`dotde: command not found`**: close the Terminal and open it again after the installation.

<a id="license"></a>
## 📄 License

MIT: you can use, change and share DotDE freely. See the [LICENSE](LICENSE) file.

---

<a id="it"></a>
<a id="indice"></a>
## 📑 Indice

- [✨ Cos'è](#cose)
- [🚀 Installazione](#installazione)
- [🧭 Come si usa](#come-si-usa)
- [🛟 Problemi comuni](#problemi-comuni)
- [📄 Licenza](#licenza)

---

<a id="cose"></a>
## ✨ Cos'è

DotDE è un programma da terminale che salva l'aspetto e le impostazioni del tuo desktop in un unico file, e le rimette a posto quando ti servono, per esempio dopo aver formattato il computer.

Salva:

- l'aspetto (tema, colori, icone, font, sfondo), pannelli e widget, il comportamento delle finestre, le scorciatoie da tastiera, le impostazioni di mouse e tastiera;
- se vuoi, le impostazioni di altri programmi che usi;
- l'elenco dei programmi che hai installato, così può proporti di reinstallarli.

Funziona con KDE Plasma, GNOME, XFCE, Hyprland e Sway, su Arch, Debian, Ubuntu, Fedora, openSUSE e le distribuzioni derivate. Parla italiano e inglese.

Non salva mai password, chiavi o dati del browser. Prima di cambiare qualcosa conserva una copia delle tue impostazioni attuali, così puoi sempre tornare indietro.

<a id="installazione"></a>
## 🚀 Installazione

Ti serve Linux con Python 3.11 o più recente, già presente nelle distribuzioni recenti.

1. Apri il Terminale e installa **pipx** (lo strumento che installa DotDE) e **git**, con il comando per il tuo sistema:

   ```bash
   sudo pacman -S python-pipx git    # Arch, CachyOS, Manjaro
   sudo apt install pipx git         # Debian, Ubuntu, Mint
   sudo dnf install pipx git         # Fedora
   ```

   Sulle altre distribuzioni cerca *pipx* e *git* nel gestore dei programmi.

2. Poi incolla questi due comandi:

   ```bash
   pipx ensurepath
   pipx install git+https://github.com/alexis-82/dotde
   ```

3. Chiudi il Terminale e riaprilo.

<a id="come-si-usa"></a>
## 🧭 Come si usa

Apri il Terminale e scrivi `dotde`. Compare un menu: ti muovi con le frecce e premi Invio per scegliere. Negli elenchi con le caselle premi Spazio per mettere o togliere la `[x]`: vengono usate solo le voci con la `[x]`. Scegli **← Indietro** in fondo a un elenco per tornare indietro.

**Prima di formattare**

1. Scegli **Esporta la mia configurazione**.
2. Scegli cosa salvare (è già tutto selezionato) e dove mettere il file.
3. Copia il file che ottieni (`dotde-….tar.gz`) su una chiavetta USB o nel cloud.

**Dopo aver reinstallato**

1. Installa di nuovo DotDE e rimetti il file sul computer.
2. Scrivi `dotde`, scegli **Importa una configurazione** e indica il file.
3. DotDE ti propone prima di reinstallare i tuoi programmi, poi ti mostra cosa cambierà e ti chiede conferma.
4. Su KDE Plasma le impostazioni vengono applicate al prossimo accesso: DotDE ti propone di uscire dalla sessione. Su XFCE ti chiede di uscire e di lanciarlo da una console testuale (Ctrl+Alt+F3).

Hai cambiato idea? Scegli **Annulla ultimo import** per riavere le impostazioni di prima.

Importa solo file creati da te: un file fatto da altri potrebbe contenere impostazioni che avviano programmi.

<a id="problemi-comuni"></a>
## 🛟 Problemi comuni

- **"Il ripristino al login non è riuscito"**: DotDE te lo dice all'avvio successivo, insieme al file con i dettagli. Importa di nuovo il file, oppure scegli **Annulla ultimo import**.
- **Alcuni programmi vengono saltati**: non esistono più nella tua distribuzione. Installa tu un sostituto.
- **I programmi non vengono installati automaticamente**: il file viene da un'altra famiglia di distribuzioni (per esempio da Arch a Ubuntu). DotDE ti mostra l'elenco, così puoi installarli tu.
- **`dotde: command not found`**: chiudi il Terminale e riaprilo dopo l'installazione.

<a id="licenza"></a>
## 📄 Licenza

MIT: puoi usare, modificare e condividere DotDE liberamente. Vedi il file [LICENSE](LICENSE).
