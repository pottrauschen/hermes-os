# Testumgebung: Bauen und Booten im Homelab

Wo hermes-os gebootet wird, solange kein Rechner dafür frei ist: auf dem
Proxmox-Host `<proxmox-host>`, nach dem Muster des Projekts ainux. Das Image kommt fertig
aus der CI; im Homelab entsteht nur der Datenträger daraus, und der bootet in
einer Test-VM. Der Weg über `bootc switch` auf einem echten Rechner steht in der
README und bleibt der Weg für Geräte.

## Beteiligte

| Was | Wo | Eigenschaften |
|---|---|---|
| Bau-VM `ainux-build` | VM 110 auf `<proxmox-host>`, `<user>@<bau-vm>` | Fedora Cloud 44, rootful Podman, bootc-image-builder, 4 Kerne, 4 GB, 80 GB Platte |
| Test-VM `hermes-test` | VM 112 auf `<proxmox-host>`, `<user>@<test-vm>` (DHCP) | q35, OVMF ohne Secure Boot, 4 Kerne, 8 GB; RTX 3060 per Passthrough (`hostpci0: 0000:0c:00,pcie=1`), `vga: none`, Bild am HDMI der 3060, Tastatur und Maus über den KVM-Umschalter (`usb0: host=5-6.1.4.1`); bootet `hermes-os-nvidia`, seit 2026-09-27 das private Image darauf |
| Zwischenablage für die Platte | `<proxmox-host>`, `/zfspool0/iso/transfer/` | auf dem ZFS-Pool, nicht in `/tmp` |

Die Bau-VM gehört dem Projekt ainux und wird mitbenutzt (Entscheidung
2026-09-26). hermes-os legt dort nur `~/hermes-os` an und das gepullte Image im
root-Speicher von Podman; die Platte wurde dafür von 40 auf 80 GB vergrößert.

**110 und 112 laufen nie gleichzeitig.** Der Host hat rund 9 bis 15 GB RAM
frei, je nachdem, welche anderen VMs laufen. Der Ablauf ist deshalb seriell:
bauen, 110 stoppen, 112 starten. Wer 110 während des Baus stoppt, bricht ihn
ab; der Neustart wiederholt nur den Datenträgerbau, nicht den Pull.

## Ablauf

1. **Image auf die Bau-VM holen.** Auf 110, in den root-Speicher, weil der
   Builder nur den sieht:

   ```sh
   sudo podman pull ghcr.io/pottrauschen/hermes-os:latest
   ```

2. **Datenträger bauen.** `~/hermes-os/build-qcow2.sh` auf 110 ruft den
   bootc-image-builder genauso auf wie das Makefile-Ziel `qcow2`, nur ohne
   Repo. Die Konfiguration `~/hermes-os/config.toml` entspricht einer
   `disk.local.toml`: Nutzer `admin` in `wheel`, Passwort und der
   SSH-Schlüssel des Arbeitsplatzes. Das Skript nennt vor dem Bau Kennung,
   Digest und Version des Images; die Zeile gehört gelesen und mit
   `bootc status` in der gebooteten VM verglichen. Ergebnis:
   `~/hermes-os/output/qcow2/disk.qcow2`.

3. **Platte importieren.** Auf `<proxmox-host>` als root: `/root/hermes-import.sh` holt
   die Datei per SSH von 110 auf den ZFS-Pool, importiert sie mit
   `qm importdisk` nach `vmdata`, hängt sie als `scsi0` mit
   `discard=on,iothread=1` ein, setzt die Bootreihenfolge und löscht die
   Zwischendatei. Der RSA-Schlüssel von `root@pve` ist dafür auf 110 in den
   `authorized_keys` von `admin` eingetragen; die Bau-VM selbst hat keinen
   privaten Schlüssel und kommt an keinen anderen Rechner heran.

4. **Booten.** `qm stop 110`, `qm start 112`. Die Adresse liefert der
   Gast-Agent, den Aurora mitbringt:

   ```sh
   qm guest cmd 112 network-get-interfaces
   ```

5. **Prüfen.** Die SSH-Teile der Boot-Checkliste (Abschnitt unten)
   erledigt `tests/boot-check.sh`:

   ```sh
   ssh <user>@<adresse> 'bash -s' < tests/boot-check.sh <kennung-aus-schritt-2>
   ```

   First-Login-Terminal, Freigabe-Dialog, Sprache und der AT-SPI-Baum brauchen
   die grafische Sitzung: Proxmox-Konsole von VM 112, Anmeldung als `admin`.

Der Datenträgerbau ist nur für den allerersten Boot nötig. Die gebootete VM
trägt `ghcr.io/pottrauschen/hermes-os:latest` als Ursprung, das Paket ist
öffentlich; jede weitere Fassung kommt wie auf einem echten Gerät:

```sh
sudo bootc upgrade          # holt latest, staged das Deployment
systemctl reboot            # aktiviert es
```

Am 2026-09-26 brauchte das für eine geänderte Schicht (450 MB) 38 Sekunden
plus Neustart in unter einer Minute. Wer trotzdem eine neue Platte baut: die
alte wird durch `qm set --scsi0` zum `unused0` und belegt weiter Platz auf
`vmdata`; nach dem Tausch `qm set 112 --delete unused0`.

## GPU-Passthrough: RTX 3060 an VM 112

Seit 2026-09-26 hängt die RTX 3060 des Hosts (`0c:00`, GA106, 12 GB) an der
Test-VM, damit Whisper, Sprachausgabe und lokale Modelle auf der GPU laufen
können. Der Host war vorbereitet (`amd_iommu=on iommu=pt`, beide
NVIDIA-Karten an `vfio-pci`, eigene IOMMU-Gruppen); die Schritte waren:

1. In der laufenden VM auf die NVIDIA-Variante wechseln, nur gestaged:
   `sudo bootc switch ghcr.io/pottrauschen/hermes-os-nvidia:latest`
   (36 neue Schichten, 2,4 GB, rund fünf Minuten).
2. VM herunterfahren (`sudo systemctl poweroff` in der VM; `qm shutdown`
   kann an der Plasma-Abfrage hängen), dann auf dem Host
   `qm set 112 -hostpci0 0000:0c:00,pcie=1` und `qm start 112`.
   Die Audio-Funktion `0c:00.1` kommt über die Multifunktionsangabe mit.
3. Prüfen: `nvidia-smi` meldet die Karte, `lsmod` zeigt `nvidia`,
   `nvidia_drm`, `nvidia_modeset`, `nvidia_uvm`; Treiber 615.71.09 mit
   Lizenz „Dual MIT/GPL", also die offenen Kernelmodule.
   `tests/boot-check.sh 44.20260922.1.20260926` meldete keine harten Fehler.

Zuerst lief die VM ohne `x-vga` und mit `vga: virtio`: Die Proxmox-Konsole
zeigte den Desktop, die 3060 war reine Rechenkarte. Seit dem 2026-09-27 steht
VM 112 auf `vga: none`: Plasma läuft auf der 3060, das Bild kommt über deren
HDMI an den Bildschirm am KVM-Umschalter, Tastatur und Maus über den
durchgereichten USB-Anschluss. Die Proxmox-Konsole bleibt damit schwarz, und
`qm monitor … screendump` liefert nichts; bedient wird die Sitzung von hier
aus wie im Abschnitt „VM 112 von hier bedienen“.

Randbedingungen: Die 3060 steht auch in den Configs von VM 105 und 107
(Render-VM); solange sie an 112 hängt, startet keine der beiden. Der
Gast-RAM (8 GB) ist bei Passthrough fest gepinnt. Die Quadro P620 (`04:00`,
Pascal) taugt nicht: `aurora-dx-nvidia-open` unterstützt erst Turing, und
NVIDIA beendet die Pascal-Unterstützung mit der 580er-Linie.

## VM 112 von hier bedienen

Die VM hat keine Proxmox-Konsole mehr (`vga: none`). Vom Windows-PC aus geht
trotzdem alles, was man an der Sitzung braucht; die Hilfen dafür liegen in
`tests/vm-hilfen.sh`.

| Was | Wie |
|---|---|
| Anmelden am Anmeldebildschirm | auf dem Host `<proxmox-host>` als root: `qm sendkey 112 shift`, dann das Passwort Taste für Taste, dann `ret`. Auf deutscher Belegung liegt `-` auf der US-Taste `slash`: `for k in h e r m e s slash o s; do qm sendkey 112 $k; done; qm sendkey 112 ret` |
| Befehle in der Sitzung | `ssh <user>@<test-vm>`, dann `. ~/hosenv.sh` (Kopie von `tests/vm-hilfen.sh`, siehe Kopf der Datei). Setzt `WAYLAND_DISPLAY`, `DBUS_SESSION_BUS_ADDRESS` und die übrige Umgebung der Plasma-Sitzung |
| Bildschirmfoto | `shot` legt `~/hos/s.png` an (`shotp` mit Zeiger), dann `scp <user>@<test-vm>:hos/s.png .` auf den PC |
| Klicken und Tippen | `VM_PASS=… prep` einmal je Sitzung (ydotool-Daemon, flache Zeigerbeschleunigung), dann `click X Y` und `paste "Text"` |
| Hermes fragen ohne Tastatur | `frage "…"` schickt die Frage ins Kontor, `frage_still "…"` antwortet als Benachrichtigung (Runner des Leisten-Symbols über D-Bus) |
| Leisten-Symbol zeigen | `/usr/libexec/hermes-os-tray --show` (reicht an die laufende Instanz weiter) |

Wer an der VM sitzt, sieht, was diese Hilfen tun: Fenster öffnen sich, der
Zeiger bewegt sich. Vorher Bescheid sagen. Für Bilder von Oberflächen, die
niemanden stören sollen, gibt es die Offscreen-Tests
(`docs/entwicklung.md`, „Oberflächen ohne Bildschirm prüfen“).

## Stolperfallen

- **`/tmp` auf dem Host ist ein tmpfs im RAM.** Die ainux-Doku legt die Platte
  dort ab, bei 3,5 GB. Das hermes-os-qcow2 ist ein Vielfaches davon und würde
  den RAM verdrängen, den die Test-VM braucht. Deshalb der ZFS-Pool.
- **Aurora deklariert `btrfs` als Wurzeldateisystem** in
  `/usr/lib/bootc/install/20-aurora.toml`. Das Makefile setzt `--rootfs`
  trotzdem, weil das nackte Universal-Blue-Basis-Image ohne die Angabe
  abbricht und die Wahl so sichtbar bleibt.
- **Neue Platte, neue Wirtsschlüssel.** Nach jedem Tausch meldet `ssh`
  „REMOTE HOST IDENTIFICATION HAS CHANGED". Richtig ist
  `ssh-keygen -R <adresse>`, nicht das Abschalten der Prüfung.
- **`sudo` in der Test-VM fragt nach dem Passwort.** Prüfungen, die root
  brauchen, laufen deshalb über `ssh -t` mit Eingabe oder an der Konsole.
- **Secure Boot ist in VM 112 aus**, weil das Image noch nicht signiert ist.
  Sobald `SIGNING_SECRET` und `cosign.pub` da sind, gehört das getestet.
- **SSH ist im Image aus.** Aurora startet sshd nicht, und der Datenträger
  erbt das. Über den Gast-Agenten geht nur `systemctl enable sshd`, also der
  Symlink, nicht der Start: der Agent läuft unter einem SELinux-Kontext, der
  systemctl nicht bedienen darf. Ein Neustart aktiviert den Dienst; an der
  Konsole reicht `sudo systemctl enable --now sshd`.
- **Auroras Ersteinrichtung startet trotz vorhandenem Nutzer.**
  `plasma-setup.service` läuft, solange `/etc/plasma-setup-done` fehlt; der
  Builder legt den Nutzer an, den Marker nicht. Entweder den Wizard an der
  Konsole durchlaufen, der einen weiteren Nutzer anlegen will, oder als Nutzer
  `sudo touch /etc/plasma-setup-done` und neu starten. Dann erscheint der Login
  von plasmalogin, Auroras Login-Manager anstelle von SDDM.
- **Kernel-Zeile mit `console=ttyS0`.** Der Builder trägt sie ein; ohne
  serielle Schnittstelle meldet agetty alle zehn Sekunden einen Fehler. VM 112
  hat deshalb `serial0: socket`, und `qm terminal 112` liefert eine Konsole.
- **Journal-Rauschen aus Aurora.** udev löst beim frühen Boot Gruppen wie
  disk, kvm, tss und plugdev nicht auf, dazu kommen zwei SELinux-Hinweise
  (lsblk gegen die userdb, chcon mit mac_admin). Nichts davon stammt aus der
  hermes-os-Schicht; `tests/boot-check.sh` filtert das Bekannte heraus.
- **Screenshots ohne Anmeldung** gingen nur mit `vga: virtio`:
  `echo "screendump /root/112.ppm" | qm monitor 112` auf dem Host,
  `/root/ppm2png.py` dort wandelt das PPM nach PNG. Mit `vga: none` bleibt
  das Bild schwarz; dann Spectacle in der Sitzung (unten).
- **Bildschirmfoto aus der Sitzung zeigt ein altes Bild**, wenn die Anzeige
  per DPMS aus ist: `spectacle --background` liefert dann den eingefrorenen
  Frame samt alter Uhr. Vorher `kscreen-doctor --dpms on` über
  `systemd-run --user`, dann stimmt das Foto; `wake` in
  `tests/vm-hilfen.sh` tut genau das.
- **ydotool tippt US-Belegung.** `ydotool type` setzt auf deutscher Tastatur
  y und z vertauscht und Sonderzeichen falsch; Text deshalb über die
  Zwischenablage (`paste`). `wl-copy` ohne offene Ausgaben starten, sonst
  hält es die SSH-Sitzung offen.
- **Ohne grafische Anmeldung stirbt das Gateway mit der SSH-Sitzung.** Nach
  einem Neustart steht die VM am Anmeldebildschirm, kein Autologin; die
  Nutzer-Units starten erst mit der Plasma-Sitzung. `systemctl --user start
  hermes-gateway` aus SSH läuft nur, solange diese Sitzung offen ist, weil
  der Nutzer-Manager ohne Linger mit der letzten Sitzung endet. Also Start
  und Test in einer SSH-Sitzung, oder an der Konsole anmelden.
- **Tastatur und Sprache kommen nicht vom Builder.** bootc-image-builder
  kennt keine Locale-Anpassung; ohne Vorgaben im Image bootet der Datenträger
  mit us-Tastatur und Englisch. Plasma liest die Tastatur aus `kxkbrc`, sonst
  aus `localectl`. KWin lauscht per KConfigWatcher: eine Änderung greift
  sofort, wenn `kwriteconfig6 --notify` schreibt, sonst erst mit der nächsten
  Anmeldung. Das D-Bus-Signal `reloadConfig` bewirkt bei KWin 6.7 nichts.

## Messwerte vom ersten Lauf (2026-09-26)

| Schritt | Wert |
|---|---|
| Pull des Images auf 110 | 6 GB komprimiert, 16,3 GB im Speicher, rund 20 Minuten |
| Datenträgerbau auf 110 | 32 Minuten mit 4 Kernen und 4 GB |
| qcow2 | 7,35 GB Datei, 32 GB virtuelle Platte |
| Transfer 110 nach Host | rund 300 MB/s, unter einer Minute |
| Import nach vmdata | rund 2 Minuten |
| Boot bis Gast-Agent | rund 20 Sekunden, SSH unmittelbar danach |

Gebootet hat `44.20260922.1.20260925` mit Kernel 7.1.10; das Prüfskript meldete
keine harten Fehler. Spätere Fassungen kamen per `bootc upgrade` (450 MB, 38 s)
und `bootc switch` auf die NVIDIA-Variante (2,4 GB, rund fünf Minuten).

## Boot-Checkliste, Stand 2026-09-26

| Punkt | Ergebnis |
|---|---|
| First-Login | Bestanden. Config aus Vorlage, Plugin und Skill verlinkt, Plugin enabled. Einrichtung über den Assistenten aus `~/hos` (Testfassung, im Image ab dem nächsten CI-Lauf), OpenRouter mit Schlüssel. Nach dem Upgrade auf `44.20260922.1.20260926` legte das Skript beim Login `API_SERVER_KEY` in `.env` an und schaltete das Gateway ein. |
| Leisten-Symbol (`docs/systemagent.md`) | Automatischer Teil bestanden: Symbol startet per Autostart, legt das Gespräch `hermes-os-tray` am API-Server an, keine QML-Fehler im Journal, `/health` antwortet, `--show` einer zweiten Instanz endet sofort (Weiterreichen). Offen, nur am Bildschirm prüfbar: Symbolfarbe, Meta+H, Antwort im Fenster, Freigabe-Kasten und Benachrichtigung. |
| NVIDIA-Variante | Bestanden am 2026-09-26 mit der RTX 3060 per Passthrough: `hermes-os-nvidia` bootet, offene Kernelmodule 615.71.09 geladen, `nvidia-smi` zeigt 12 GB. Ob Whisper und Piper die GPU nutzen, ist noch nicht geprüft. |
| `hermes` im Terminal, Plugin geladen | Bestanden. `hermes chat -q` mit der Frage nach Deployments lieferte Image-Referenz und Version aus `os_status`. |
| `app_launch` | Bestanden. Aus der Sitzung gestartet (`systemd-run --user`), Konsole erschien. Per SSH ohne Sitzungsumgebung nicht testbar. |
| Freigabe-Dialog | Offen, nur interaktiv prüfbar: `sudo bootc upgrade --check` im Chat muss fragen, `flatpak install` nicht. |
| Gateway | Bestanden. Der Assistent ruft nach dem Speichern das First-Login-Skript, das die Unit einschaltet; `enabled`/`active`, OpenRouter-Schlüssel im Credential-Pool. Seit dem 26.09. mit API-Server auf `127.0.0.1:8642`, Schlüssel aus `.env` wird akzeptiert. Hinweis im Journal: die Unit hat `TimeoutStopSec=30s`, Hermes erwartet `drain_timeout`-passende Werte („Stale systemd unit detected"); noch nicht angeglichen. |
| Sprache (`/voice on`) | Offen, braucht Mikrofon in der VM. |
| Tastatur und Systemsprache | Fehlgeschlagen am 2026-09-26 mit dem ersten Datenträger: y ergab z, Plasma auf Englisch. Ursache: der Datenträger aus dem Builder trägt weder Locale noch Tastatur, nur der Anaconda-Installer fragt danach; das Testmodell hat dann Schlüssel in `kdeglobals` und `kwinrc` erfunden. In VM 112 von Hand gesetzt, seither Vorgaben im Image und Rezeptur im Skill. Bestanden am Abend des 2026-09-26 nach `bootc upgrade` auf Digest `2eb6e1a5…`: Vorgaben unter `/etc` und `/etc/xdg` da, `localectl` meldet de/de/de, der Agent bestätigt es über `os_locale`. |
| Bibliothek (`docs/bibliothek.md`) | Bestanden am 2026-09-26: `library_list` über das Gateway im gebooteten Image nennt den Eintrag docs.kde.org; zuvor aus `~/hos` der volle Lauf mit `library_fetch` (Dolphin-Handbuch mit Quelle in 30 s). Die Seite im Fenster ist offscreen geprüft, am Bildschirm noch nicht. |
| `ujust --list` | Bestanden, acht Rezepte. |
| AT-SPI (Phase 3) | `busctl --user tree org.a11y.atspi.Registry` liefert keinen Baum; Accessibility in den KDE-Einstellungen einschalten, sobald Phase 3 beginnt. |

`hermes doctor` ist bis auf optionale Pakete grün, OpenRouter erreichbar. Ohne
Bedeutung für hermes-os: „~/.local/bin/hermes not found" (unser Launcher liegt
unter `/usr/bin`), ripgrep und Node fehlen (optional).
