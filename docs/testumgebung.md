# Testumgebung: Bauen und Booten im Homelab

Wo hermes-os gebootet wird, solange kein Rechner dafür frei ist: auf dem
Proxmox-Host `.40`, nach dem Muster des Projekts ainux. Das Image kommt fertig
aus der CI; im Homelab entsteht nur der Datenträger daraus, und der bootet in
einer Test-VM. Der Weg über `bootc switch` auf einem echten Rechner steht in der
README und bleibt der Weg für Geräte.

## Beteiligte

| Was | Wo | Eigenschaften |
|---|---|---|
| Bau-VM `ainux-build` | VM 110 auf `.40`, `stephan@192.168.1.36` | Fedora Cloud 44, rootful Podman, bootc-image-builder, 4 Kerne, 4 GB, 80 GB Platte |
| Test-VM `hermes-test` | VM 112 auf `.40`, Adresse per DHCP | q35, OVMF ohne Secure Boot, 4 Kerne, 8 GB, virtio-Grafik, USB-Tablet |
| Zwischenablage für die Platte | `.40`, `/zfspool0/iso/transfer/` | auf dem ZFS-Pool, nicht in `/tmp` |

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
   `disk.local.toml`: Nutzer `stephan` in `wheel`, Passwort und der
   SSH-Schlüssel des Arbeitsplatzes. Das Skript nennt vor dem Bau Kennung,
   Digest und Version des Images; die Zeile gehört gelesen und mit
   `bootc status` in der gebooteten VM verglichen. Ergebnis:
   `~/hermes-os/output/qcow2/disk.qcow2`.

3. **Platte importieren.** Auf `.40` als root: `/root/hermes-import.sh` holt
   die Datei per SSH von 110 auf den ZFS-Pool, importiert sie mit
   `qm importdisk` nach `vmdata`, hängt sie als `scsi0` mit
   `discard=on,iothread=1` ein, setzt die Bootreihenfolge und löscht die
   Zwischendatei. Der RSA-Schlüssel von `root@pve` ist dafür auf 110 in den
   `authorized_keys` von `stephan` eingetragen; die Bau-VM selbst hat keinen
   privaten Schlüssel und kommt an keinen anderen Rechner heran.

4. **Booten.** `qm stop 110`, `qm start 112`. Die Adresse liefert der
   Gast-Agent, den Aurora mitbringt:

   ```sh
   qm guest cmd 112 network-get-interfaces
   ```

5. **Prüfen.** Die SSH-Teile der Boot-Checkliste aus `docs/HANDOFF.md`
   erledigt `tests/boot-check.sh`:

   ```sh
   ssh stephan@<adresse> 'bash -s' < tests/boot-check.sh <kennung-aus-schritt-2>
   ```

   First-Login-Terminal, Freigabe-Dialog, Sprache und der AT-SPI-Baum brauchen
   die grafische Sitzung: Proxmox-Konsole von VM 112, Anmeldung als `stephan`.

Bei einer neuen Image-Fassung wiederholt sich der Ablauf ab Schritt 1. Die
alte Systemplatte wird durch `qm set --scsi0` zum `unused0` und belegt weiter
Platz auf `vmdata`; nach dem Tausch `qm set 112 --delete unused0`.

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
- **Screenshots ohne Anmeldung:** `echo "screendump /root/112.ppm" | qm monitor 112`
  auf dem Host; `/root/ppm2png.py` dort wandelt das PPM nach PNG.

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
keine harten Fehler.

## Boot-Checkliste, Stand 2026-09-26

| Punkt | Ergebnis |
|---|---|
| First-Login | Bestanden. Config aus Vorlage, Plugin und Skill verlinkt, Plugin enabled. Einrichtung über den Assistenten aus `~/hos` (Testfassung, im Image ab dem nächsten CI-Lauf), OpenRouter mit Schlüssel. |
| `hermes` im Terminal, Plugin geladen | Bestanden. `hermes chat -q` mit der Frage nach Deployments lieferte Image-Referenz und Version aus `os_status`. |
| `app_launch` | Bestanden. Aus der Sitzung gestartet (`systemd-run --user`), Konsole erschien. Per SSH ohne Sitzungsumgebung nicht testbar. |
| Freigabe-Dialog | Offen, nur interaktiv prüfbar: `sudo bootc upgrade --check` im Chat muss fragen, `flatpak install` nicht. |
| Gateway | Bestanden. Der Assistent ruft nach dem Speichern das First-Login-Skript, das die Unit einschaltet; `enabled`/`active`, OpenRouter-Schlüssel im Credential-Pool. Hinweis im Journal: die Unit hat `TimeoutStopSec=30s`, Hermes erwartet `drain_timeout`-passende Werte („Stale systemd unit detected"); noch nicht angeglichen. |
| Sprache (`/voice on`) | Offen, braucht Mikrofon in der VM. |
| `ujust --list` | Bestanden, acht Rezepte. |
| AT-SPI (Phase 3) | `busctl --user tree org.a11y.atspi.Registry` liefert keinen Baum; Accessibility in den KDE-Einstellungen einschalten, sobald Phase 3 beginnt. |

`hermes doctor` ist bis auf optionale Pakete grün, OpenRouter erreichbar. Ohne
Bedeutung für hermes-os: „~/.local/bin/hermes not found" (unser Launcher liegt
unter `/usr/bin`), ripgrep und Node fehlen (optional).
