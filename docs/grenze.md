# Die Grenze: was fragt, was frei läuft

Gefährliche Änderungen am laufenden System fragen, der Rest läuft frei. Das ist
eine **Systemgrenze, keine Datengrenze**: Alles im Home des Nutzers ist frei,
auch User-Units, Autostart-Einträge, `~/.ssh` und Netzwerkzugriffe.

Die eigentliche Barriere gegen Systemänderungen ist, dass der Nutzer ohne
Passwort kein Root hat (sudo, pkexec und run0 fragen danach). Der Hook sorgt
dafür, dass der Agent fragt, *bevor* er es versucht, und dass Neustart und
Herunterfahren gar nicht erst ausgeführt werden. Er erkennt Befehle, keine
Wirkungen.

Durchgesetzt an drei Stellen:

1. **System-Prompt-Abschnitt** in `plugins/hermes_os/__init__.py`, modellabhängig.
2. **`approvals.smart_policy`** in `config.yaml.default` für Hermes' Guardian,
   modellabhängig und nur für Befehle, die Hermes' eigener Detektor meldet.
3. **`pre_tool_call`-Hook** in `plugins/hermes_os/boundary.py`, deterministisch.
   Nur dieser Teil ist getestet (`tests/boundary-check.py`).

## Hook-Vertrag laut Upstream (v2026.9.24)

Quelle: `hermes_cli/plugins.py` (`_get_pre_tool_call_directive_details`,
`_resolve_block_from_details`), `hermes_cli/plugins_dispatch.py`
(`invoke_hook`), `tools/approval.py` (`request_tool_approval`,
`_run_approval_gate`).

| Rückgabe | Wirkung |
|---|---|
| `None` | frei |
| `{"action": "block", "message": …}` | Veto, die Meldung wird zum Werkzeug-Ergebnis. Ohne `message` ignoriert Hermes das Veto. Ein `block` irgendeines Plugins schlägt jedes `approve`. |
| `{"action": "approve", "message": …, "rule_key": …}` | menschlicher Freigabe-Dialog (CLI-Prompt, Gateway `/approve`, Leisten-Symbol). Geht nicht über den Guardian, ein Mensch entscheidet. `rule_key` ist die Körnung für „immer erlauben“. |
| `{"action": "modify", "args": …}` | ändert die Argumente, hier nicht benutzt |

Einen Wert `deny` gibt es nicht, verweigert wird mit `block`.

- **Exception im Hook:** Hermes selbst macht daraus ein `block` (Policy-Hook,
  fail-closed), ebenso bei Zeitüberschreitung (`plugins.hook_callback_timeout`,
  Vorgabe 30 s). Der Hook fängt eigene Fehler vorher ab und antwortet mit
  `approve` und dem Hinweis, dass die Prüfung scheiterte: Der Nutzer entscheidet,
  statt dass der Befehl stumm scheitert.
- **Ohne Menschen:** `approve` wird in Cron, `-q` und unbeaufsichtigten
  Plattformen nach `approvals.cron_mode`, `single_query_mode` und
  `unattended_mode` entschieden (bei uns `deny`), sonst blockiert.
- **Abschalten:** `--yolo`, `/yolo` im Gateway oder `approvals.mode: off` winken
  jedes `approve` durch. `block` gilt weiter.

## Was Hermes selbst fängt

`tools/approval_detection.py`, vor jedem Terminal-Befehl, unabhängig vom Plugin.

- **Hardline, immer verweigert, auch mit yolo:** `rm -rf` auf `/`, Systemordner
  und Home, `mkfs`, `dd` auf Blockgeräte, Umleitung auf Blockgeräte, Forkbombe,
  `kill -1`, `shutdown`, `reboot`, `halt`, `poweroff`, `init 0/6`, `telinit 0/6`,
  `systemctl poweroff|reboot|halt|kexec`. Nur an Befehlsposition mit den Präfixen
  sudo, env, exec, nohup, setsid, time; `pkexec reboot`, `run0 reboot`,
  `loginctl poweroff` und D-Bus-Aufrufe kennt die Liste nicht.
- **Gefährlich, fragt (mit `mode: smart` erst der Guardian):** `rm -r`,
  `chmod 777`, `chown -R root`, Schreiben per `>`/`tee`/`cp`/`mv` nach `/etc/`,
  `~/.ssh`, Shell-RC-Dateien und Zugangsdaten, `systemctl stop|restart|disable|mask`,
  `curl | sh`, `find -delete`, `xargs rm`, `sudo -S` ohne hinterlegtes Passwort.
- **Datei-Werkzeuge** (`write_file`, `patch`): Schreiben unter `/etc/`, `/boot/`,
  `/usr/lib/systemd/` fragt.

## Was nur am Hook hängt

Gruppe `power` wird verweigert, alle anderen fragen.

| Gruppe | Beispiele |
|---|---|
| `power` | `reboot`, `poweroff`, `halt`, `shutdown`, `systemctl reboot\|poweroff\|halt\|kexec\|soft-reboot\|rescue\|emergency`, `systemctl start\|isolate\|set-default reboot.target` (und die anderen Power-Targets), `loginctl poweroff`, `init 0/1/6`, login1-, systemd1- und KDE-Shutdown über `busctl`/`dbus-send`/`gdbus`/`qdbus` |
| `sleep` | `systemctl suspend\|hibernate`, `loginctl suspend` |
| `sudo` | `sudo`, `pkexec`, `doas`, `run0`, `su -c`, `machinectl shell` mit einem Befehl außerhalb der Allowlist; `distrobox --root` |
| `root-shell` | `sudo -i`, `sudo -s`, `sudo bash`, `su`, `pkexec`/`run0` ohne Befehl, `machinectl shell .host`, `sudo chroot /sysroot` |
| `image` | `bootc upgrade\|switch\|rollback …`, `rpm-ostree install\|override\|kargs …`, `ostree admin …` (außer `status`), `systemd-sysext merge`, `ujust update` und verwandte |
| `ujust` | jedes Rezept außer `hermes-*`, `changelogs` und reinen Anzeigen (`--list`, `--show`) |
| `services` | `systemctl start\|enable\|mask …` ohne `--user`, `systemd-run` ohne `--user`, `machinectl start …`, `service`, `init 3` |
| `system-files` | Umleitungen `>`/`>>`/`&>`/`>&` und Dateibefehle (`tee`, `cp`, `mv`, `install`, `ln`, `rm`, `chmod`, `sed -i`, `touch`, `mkdir`, `curl -o`, `wget -O`, `tar -C`, `unzip -d`, `find -delete` …) mit Ziel in einem Systempfad (unten); `sudoedit` |
| `network` | `firewall-cmd`, `nft`, `iptables` (außer Anzeigen), `nmcli` mit Änderungen (Verbindungen, Funk, WLAN verbinden) |
| `users` | `useradd`, `passwd`, `chsh`, `visudo`, `authselect` … |
| `boot` | `grubby`, `dracut`, `kernel-install`, `bootupctl`, `mokutil`, `efibootmgr` mit Änderungen, `bootctl` außer `status` |
| `disks` | `fdisk`, `parted`, `mkfs.*`, `wipefs`, `cryptsetup`, `mount`/`umount` mit Operanden, `dd of=/dev/…` |
| `system-config` | `localectl\|timedatectl\|hostnamectl set-*`, `hostnamectl hostname X`, `sysctl -w`, `date -s`, `hwclock -w`, `loginctl enable-linger` |
| `flatpak-system` | `flatpak install\|remove\|update … --system` |
| `ssh`, `kernel`, `security`, `session` | `ssh-keygen`, `ssh-copy-id`; `modprobe`, `rmmod`; `setenforce`, `semanage`, `setcap`, `update-crypto-policies --set`; `loginctl terminate-*`, `kill -9 -1` |
| `firmware` | `fwupdmgr update\|install\|…` (polkit lässt das in aktiven Sitzungen oft ohne Passwort zu) |

`image` umfasst auch `pkcon install|update|remove` und `just -f /usr/share/ublue-os/justfile …`
(dort gelten die ujust-Regeln). `bootc upgrade --check` und `rpm-ostree upgrade
--check|--preview` bleiben frei, auch mit sudo; `reboot --help` ebenso.

**Systempfade** für Umleitungen und Dateibefehle: `/`, `/etc`, `/usr`, `/boot`, `/var`,
`/ostree`, `/sysroot`, `/root`, `/opt`, `/srv`, `/proc`, `/sys`, `/dev`, `/run`, `/lib`,
`/bin`, `/sbin`. Ausgenommen: `/var/home` (das Home), `/var/tmp`, `/run/user`,
`/run/media`, `/dev/null`, `/dev/zero`, `/dev/std*`, `/dev/tty`, `/dev/fd`, `/dev/pts`,
`/dev/shm`, `/dev/tcp`, `/dev/udp`, `/proc/self/fd`.

**Root-Shells schreiben überall als Root:** In `sudo sh -c '…'`, `su -c`, `pkexec sh -c`,
`sudo -i …` fragt jede schreibende Umleitung, auch ins Home; frei bleiben nur `/dev/null`,
`/dev/std*`, `/dev/fd`, `/dev/tty`.

Der Klassifikator zerlegt den Befehl wie eine Shell (Anführungszeichen,
Escapes, Zeilenfortsetzung, Tabs, `;`, `&&`, `||`, `|`, `&`, Klammern,
Heredocs, Here-Strings, `$(…)`, Backticks, `<(…)`) und entschachtelt rekursiv
`sh -c`/`bash -c`, `eval`, `xargs`, `find -exec`, `env`, `nice`, `nohup`,
`timeout`, `time`, `exec`, `command`, `watch`, `stdbuf`, `ionice`, `setsid`,
`flock`, `script -c`, `strace`, `ltrace`, `gdb --args`, `unshare`, `setarch`,
`prlimit`, `runuser`, Terminals mit `-e` (`konsole`, `xterm` …),
`systemd-run --user`, `flatpak-spawn --host`, `distrobox-host-exec`,
`host-spawn`, `toolbox run --host`, `nsenter`, `chroot`, `machinectl shell`.
Schlüsselwörter (`if`, `then`, `do`, `{`, `!`, `function f`, `coproc`) werden
übersprungen, `$'…'` wie in Bash aufgelöst (`\xHH`, oktal, `\u`). Text, der per
`echo`/`printf`, Heredoc, Here-String oder Prozess-Substitution (`bash <(…)`,
`source <(…)`) in eine Shell oder in `at`/`batch` fließt, wird ebenfalls geprüft.
Pfade werden normalisiert (`//etc/./x`, `/usr/../etc`). Die Prüfung läuft in
linearer Zeit; `tests/boundary-check.py` misst das mit langen Eingaben, weil
Hermes einen hängenden Hook nach 30 s zwar blockt, den Worker aber weiterlaufen lässt.

**Werkzeuge:** Geprüft werden `terminal` (`command`) und `process_manage` mit
`write`/`submit` (`data`, Text, der in einen laufenden Prozess getippt wird, etwa in
eine Hintergrund-Shell).

Die Freigabe-Körnung ist `hermes-os:<gruppe>:<befehl>`: „Immer erlauben“ für
`sudo python3` erlaubt nicht zugleich `sudo rm`.

## Allowlist: frei auch mit Root-Rechten

Hinter `sudo`, `pkexec`, `doas`, `run0` und `su -c` bleiben reine Lesebefehle
frei: `journalctl` (ohne `--vacuum`, `--rotate`, `--flush`), `dmesg` (ohne
`-C`, `-c`), `cat`, `less`, `more`, `head`, `tail`, `grep`, `wc`, `file`,
`stat`, `ls`, `tree`, `find` (ohne `-exec`, `-delete`), `lsblk`, `lspci`,
`lsusb`, `lsmod`, `lscpu`, `lsof`, `findmnt`, `df`, `du`, `blkid`, `diff`,
Prüfsummen, `systemctl status|show|cat|is-*|list-*`, `bootc status`,
`rpm-ostree status`, `ostree admin status`, `nmcli` ohne Änderung,
`firewall-cmd --list-*|--get-*|--query-*|--state`, `nft list`,
`iptables -L|-S`, `ip` ohne Änderung, `localectl|timedatectl|hostnamectl`
ohne Setzen, `loginctl list-*|show-*`, `fdisk -l`, `parted … print`,
`bootctl status`, `efibootmgr` ohne Änderung, `fwupdmgr get-*`.

Ohne Root bleibt alles frei, was keine Gruppe trifft: `systemctl --user`,
`flatpak install --user`, `flatpak run`, `podman`, `distrobox create/enter`,
`grep -r /etc/…`, `cat /etc/os-release`, `ls /usr/share`, `kwriteconfig6`,
`git`, alles im Home. `flatpak install` ohne `--system` bleibt ebenfalls frei,
obwohl Aurora dann systemweit installiert: Das ist gewollt (Apps sind frei).

## Bekannte Restlücken

Der Hook sieht den Befehlsstring, nicht was er bewirkt.

- **Interpreter und Skripte:** `python3 -c "os.system('sudo reboot')"`, ein
  Shell-Skript im Home, `make`, `npm run`. Mit sudo davor fragt es; ohne sudo
  scheitert die Systemänderung am fehlenden Root.
- **Andere Werkzeuge:** `execute_code` prüft der Hook nicht, Hermes fragt dort in
  Gateway und CLI selbst. `cronjob_manage` mit `script` führt eine Skriptdatei nach
  Plan aus; deren Inhalt sieht der Hook nicht. `process_manage` sieht er nur bei
  `write`/`submit`, nicht was ein schon laufender Prozess sonst tut. `write_file` und
  `patch` bewacht Hermes selbst für `/etc`, `/boot`, `/usr/lib/systemd`.
- **Shell-Text aus anderen Quellen** als `echo`/`printf`, Heredoc und Here-String:
  `base64 -d … | sh` fängt Hermes' Detektor, `curl … | sh` ebenso; `cat datei | sh`
  und Ähnliches nicht.
- **Indirektion:** Befehlsnamen aus Variablen (`$CMD`), Aliase und Funktionen
  aus früheren Aufrufen, Globs in Pfaden (`/et?/x`), relative Pfade bei
  Arbeitsverzeichnis unter `/etc` (`workdir` des Werkzeugs).
- **Andere Wege zu polkit:** `gdbus`/`busctl` für andere Aktionen als
  Energie, grafische Werkzeuge, die selbst nach dem Passwort fragen.
- **Fremde Rechner:** `ssh nas sudo reboot` betrifft einen anderen Rechner und
  bleibt frei.
- **Freigabe abgeschaltet:** Mit yolo oder `approvals.mode: off` läuft jedes
  `approve` durch; nur `power` bleibt verweigert.
- **Weitere Hüllen:** Werkzeuge, die oben nicht aufgezählt sind (etwa `parallel`,
  `tmux send-keys`, `expect`, `make`), verdecken den Befehl dahinter; ohne sudo
  fehlt ihm das Root.

## Pflege

Neue Fälle gehören in `tests/boundary-check.py` (`CASES`). `make lint` prüft
sie ohne Hermes, `tests/venv-smoke.sh` und das Gate (`80-validate.sh`)
schicken dieselbe Liste durch den echten Plugin-Loader des Releases. Vor einem
Hermes-Bump den Vertrag oben gegen `hermes_cli/plugins.py` prüfen.
