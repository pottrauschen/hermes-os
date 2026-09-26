# hermes-os — Arbeitsregeln und Doc-Map

Atomares KDE-Linux (Aurora DX, Fedora bootc, Wayland) mit Hermes Agent als
Systembestandteil. Was das ist und wie man es baut, steht in `README.md`.
Stand, Entscheidungen, offene Punkte und Stolperfallen liegen nicht hier,
sondern im Second Brain: `/hole hermes-os` lädt sie, `/handoff` sichert sie.

## Doc-Map

| Datei | Zweck |
|---|---|
| `README.md` | Was das System kann, Aufbau, die Grenze, Bauen, erster Login, Status |
| `CLAUDE.md` | diese Datei: Arbeitsregeln und Doc-Map |
| `docs/testumgebung.md` | Bauen und Booten im Homelab: Bau-VM 110, Test-VM 112, Import, Stolperfallen, Messwerte, Boot-Checkliste |
| `docs/einrichtung.md` | Einrichtungsassistent, Brücke in die Hermes-Venv, Abo-Frage, Plan für das Dashboard |
| `docs/phase3-desktop.md` | Phase 3, Desktop-Steuerung auf Basis von agent-cu |
| `files/system/usr/share/hermes-os/skills/hermes-os-system/SKILL.md` | Skill für den Agenten, wird ins Image kopiert; keine Projekt-Doku, Ausnahme in `.doku-check-ignore` |

## Arbeitsregeln

- **Ablauf einer Änderung:** `make lint` lokal, Commit, Push auf `main`.
  CI baut beide Varianten mit Validierungs-Gate (`files/scripts/80-validate.sh`)
  und Tests (`files/scripts/89-tests.sh`). Booten nur im Homelab nach
  `docs/testumgebung.md`; der Windows-PC kann keine VM fahren.
- **Was ins Image kommt, liegt unter `files/system/`**, Build-Schritte
  nummeriert unter `files/scripts/`. Beide Dockerfiles bleiben bis auf die
  FROM-Zeile identisch, `make lint` prüft das.
- **Hermes ist gepinnt** (`HERMES_REF` im Dockerfile, Linie 0.21.x). Vor einem
  Bump `tests/venv-smoke.sh`, `hermes-os-setup --check` und
  `tests/setup-gui-check.py` laufen lassen; die Brücke des Assistenten nutzt
  interne Hermes-Helfer ohne Stabilitätszusage.
- **Assistent ohne neues Image testen:** `tests/setup-gui-check.py` rendert
  offscreen, jede QML-Warnung ist ein Fehler. In der VM eine Testfassung aus
  dem Home starten (`systemd-run --user … -p ExitType=cgroup`), `HERMES_HOME`
  auf ein Wegwerfverzeichnis; `/tmp` ist nach jedem Neustart leer.
- **Windows-Arbeitsplatz:** Arbeitsbaum CRLF, Index LF. Vor dem Übertragen in
  die VM `sed 's/\r$//'`; Skripte mit `sed 's/\r$//' | bash -n` prüfen;
  Dateien mit Apostrophen nicht per Heredoc schreiben.
- **Claude fragt vorher** bei: VMs anderer Projekte anfassen (Bau-VM 110
  gehört ainux), Neustart oder Stopp von VMs, Geheimnissen in Dateien
  (`disk.local.toml` ist ignoriert, `disk.toml` nur Muster), und bei allem,
  was Bedingungen von Anbietern berührt. Kein Claude-Abo in Hermes, siehe
  `docs/einrichtung.md`.
- **Kein Session-Wissen als Datei.** Übergaben, Befunde und Pläne mit Datum
  gehören ins Brain; im Repo bleibt, was zum Code gehört und gepflegt wird.
