# Dashboard: Hermes' Web-Oberfläche als Fenster

Stand: 2026-09-27. Hermes bringt mit `hermes dashboard` eine eigene
Web-Oberfläche mit: Modelle und Schlüssel, Sessions, Cron, Plugins, Skills,
Umgebungsvariablen, Systemstatus. In hermes-os ist sie ins Image gebaut und
als Fenster erreichbar, weil im Image kein Browser liegt. Gebaut, durch
`make lint` und den Test gegen Attrappen gelaufen; das Frontend lokal mit
Node 22 gebaut; das Fenster offscreen mit echtem QtWebEngine gegen das echte
`hermes dashboard` gefahren; das Gate wiederholt beides im Image-Build. Am
27.09. lief das Fenster in einer Einzelprüfung in der Plasma-Sitzung von
VM 112, im Alltag noch nicht (siehe [Testen](#testen)).

## Was es tut

- **Menüeintrag „Hermes-Dashboard"**, Menüpunkt „Dashboard öffnen" am
  Leisten-Symbol, Knopf „Dashboard öffnen" auf der Fertig-Seite des
  Assistenten, `ujust hermes-dashboard`: alle starten
  `/usr/libexec/hermes-os-dashboard`.
- Das Fenster prüft, ob auf `127.0.0.1:9119` schon ein Dashboard antwortet.
  Wenn ja, zeigt es das. Wenn nein, startet es `hermes dashboard --no-open
  --skip-build --port 9119` aus der Venv in einem eigenen User-Scope, zeigt
  „Dashboard startet…" und lädt die Seite, sobald `/api/health` antwortet.
- Beim Schließen beendet es den Server, aber nur, wenn es ihn selbst
  gestartet hat. Ein Dashboard, das jemand im Terminal gestartet hat, bleibt.
  Stirbt das Fenster hart, beendet Hermes' eigener Eltern-Watchdog
  (`HERMES_PARENT_PID`) den Server von selbst.
- Kommt der Server nicht hoch, oder bricht die Seite weg, erscheint eine
  Fehlerseite mit Ursache, den letzten Zeilen des Servers, dem Stand des
  Gateways und einem Knopf „Erneut versuchen". Die Leiste hat „Zurück" und
  „Neu laden".

Auf Loopback braucht das Dashboard keine Anmeldung: Hermes legt bei jedem
Start ein Sitzungs-Token in die ausgelieferte `index.html`, und das
Auth-Gate mit Login-Seite greift nur bei einem Bind auf eine andere Adresse.

## Dateien

| Was | Wo |
|---|---|
| Node-Stufe `webbuild`, baut das Frontend | `Dockerfile`, `Dockerfile.nvidia` (identisch bis auf die Aurora-Zeile) |
| Frontend in die Hermes-Installation legen, PySide6 sichern | `files/scripts/15-dashboard.sh` |
| Fenster (PySide6, QtWebEngine) | `files/system/usr/libexec/hermes-os-dashboard` |
| Server starten, prüfen, beenden (ohne Qt) | `files/system/usr/share/hermes-os/dashboard/dashboard_server.py` |
| Menüeintrag | `files/system/usr/share/applications/hermes-os-dashboard.desktop` |
| ujust-Rezept `hermes-dashboard` | `files/system/usr/share/hermes-os/hermes-os.just` |
| `HERMES_WEB_DIST` für Launcher und Units | `files/scripts/10-hermes.sh`, `files/system/usr/lib/environment.d/60-hermes-os.conf` |
| Test gegen Attrappen | `tests/dashboard-check.py` |
| Fenster offscreen gegen den echten Server | `tests/dashboard-gui-check.py` |
| Gate | `files/scripts/80-validate.sh`, Abschnitt 7l |

Im Image: `/usr/lib/hermes-agent/hermes_cli/web_dist` (Frontend mit Stempel
`.hermes-os-web`), `/usr/libexec/hermes-os-dashboard`,
`/usr/share/hermes-os/dashboard/dashboard_server.py`.

## Wie Hermes das Dashboard baut und startet

Aus dem Quelltext von Hermes 0.21.5 (Tag v2026.9.24), Stand 2026-09-26:

- **Frontend**: `web/` im Hermes-Repo, React mit Vite, Workspace `web` des
  Root-`package.json` (plus `apps/shared` als `file:`-Abhängigkeit). Hermes
  pinnt Node 26 (`.nvmrc`), `engines` erlaubt `^22.22.0 || ^24.11.0 ||
  >=26`. Build: `npm ci --workspace web`, dann `npm run build --workspace
  web` (`tsc -b && vite build`), Ausgabe nach `hermes_cli/web_dist`
  (`web/vite.config.ts`, `outDir`). Nur die npm-Registry wird gebraucht.
- **Server**: `hermes_cli/web_server.py` (FastAPI, uvicorn, beides
  Kernabhängigkeiten der Venv). Vorgabe `127.0.0.1:9119`, Flags `--port`,
  `--host`, `--no-open`, `--skip-build`, `--isolated`, `--status`, `--stop`.
  Läuft im Vordergrund, meldet nach dem Bind `HERMES_DASHBOARD_READY port=N`
  auf stdout, SIGTERM beendet ihn sauber.
- **Build zur Laufzeit**: Ohne `--skip-build` und ohne `HERMES_WEB_DIST` will
  `hermes dashboard` das Frontend selbst mit npm bauen, sobald der Stempel
  `~/.hermes/web-ui-build-stamp.json` fehlt, also auf jedem frischen Home.
  Mit `HERMES_WEB_DIST` (setzen Launcher und environment.d) baut es nie und
  meldet ein fehlendes `index.html` als Fehler. Der Fensterstart nimmt
  zusätzlich `--skip-build`. Damit schreibt der Server nichts unter `/usr`.
- **Zweite Instanz**: Läuft schon ein Dashboard desselben Nutzers
  (Rendezvous-Datei unter `~/.local/state/hermes/gateway-locks/`), hängt sich
  ein zweiter Start daran, druckt „already running" mit der Adresse und
  endet mit Exit 0. Fremder Prozess auf dem Port: Exit 75. Laufendes
  Dashboard mit anderem Port oder ohne Oberfläche (`hermes serve`): Exit 78.
  `dashboard_server.py` wertet alle drei Fälle aus.
- **Readiness**: `GET /api/health` antwortet ohne Token mit
  `{"ok": true, "version": …}`. `--status` endet immer mit Exit 0 und taugt
  deshalb nicht als Prüfung.
- **Gateway**: Für den Start nicht nötig. Ohne laufendes
  `hermes-gateway.service` zeigt das Dashboard das Gateway als aus, und
  Cron-Jobs laufen nicht (die tickt der Gateway). Der Chat-Tab hängt nicht am
  Gateway, sondern startet Hermes' TUI als Kindprozess, siehe Grenzen.
- **Zustandsdateien**: unter `~/.hermes` (Logs, Skills-Seed, Spawn-Ledger)
  und `~/.local/state/hermes/`. Keine PID-Datei.

## Entscheidungen

- **Eigene Node-Stufe statt Node im Build-Skript.** Node und npm gehören nicht
  ins Image; Fedoras `nodejs` in der Aurora-Stufe zu installieren und wieder
  zu entfernen ließe dnf-Spuren und Abhängigkeiten zurück, und die Version
  hinge am Basis-Image. Die Stufe `webbuild` aus `docker.io/library/node:26-
  bookworm-slim` nimmt Hermes' gepinnte Node-Linie, klont dasselbe Release
  (`HERMES_REF`, jetzt globales ARG vor der ersten Stufe) und reicht nur
  `hermes_cli/web_dist` über die ctx-Stufe weiter. Die CI liest die
  Aurora-Zeile mit `grep '^FROM ghcr.io/ublue-os/' | tail -1`, die Node-Zeile
  stört sie nicht; `make lint` prüft, dass die letzte FROM-Zeile die
  Aurora-Basis ist und beide Dockerfiles sonst gleich bleiben.
- **Fenster mit QWebEngineView und QApplication statt Kirigami.** Ein
  Browserfenster braucht keinen Kirigami-Rahmen; die Widgets-Variante ist die
  einfachste, und das Leisten-Symbol nutzt ohnehin QApplication. QtWebEngine
  muss vor der QApplication importiert sein (OpenGL-Kontext teilen). Ein
  benanntes Profil (`hermes-os-dashboard`) hält Cookies und localStorage
  unter `~/.local/share/hermes-os-dashboard`; ein Profil ohne Namen wäre
  flüchtig.
- **Server im User-Scope.** `systemd-run --user --scope --collect --quiet
  --unit=hermes-os-dashboard-<id>.scope`, wie `app_launch` im Plugin: der
  Server gehört nicht zur cgroup des Fensters, und `systemctl --user stop`
  beendet ihn samt Kindprozessen. Ohne User-Manager (Build-Container) bleibt
  der direkte Aufruf mit SIGTERM.
- **Fehlerseite, wenn das Gateway aus ist**: Das Dashboard läuft auch ohne
  Gateway; die Fehlerseite erscheint, wenn der Server selbst nicht antwortet,
  und nennt den Gateway-Stand als Hinweis. Annahme aus dem Auftrag, weil das
  Dashboard nicht am Gateway hängt.
- **PySide6 mit QtWebEngine.** `python3-pyside6` und `qt6-qtwebengine` liegen
  im Aurora-DX-Image (Layer der Kinoite-Basis, Stand 44.20260921.0), nicht
  von Aurora selbst gewählt. `15-dashboard.sh` sichert beide mit `dnf
  install`, im Normalfall ein No-op; der Import von
  `PySide6.QtWebEngineWidgets` steht in `hermes-os-dashboard --check` und
  damit im Gate.

## Testen

Ohne Qt, ohne Netz, gegen Attrappen für `hermes`, `systemd-run` und
`systemctl` (läuft überall mit Python 3.9+, auch in `make lint`):

```sh
tests/dashboard-check.py --dashboard-dir files/system/usr/share/hermes-os/dashboard \
  --launcher files/system/usr/libexec/hermes-os-dashboard \
  --desktop-file files/system/usr/share/applications/hermes-os-dashboard.desktop \
  --just-file files/system/usr/share/hermes-os/hermes-os.just
```

Geprüft werden: Start auf freiem Port und Stopp über den Scope, Übernahme
eines laufenden Dashboards ohne es zu beenden, Absturz beim Start mit
Logauszug, belegter Port (Exit 75), „already running" mit anderer Adresse,
Betrieb ohne User-Manager, Timeout ohne Doppelstart; dazu Desktop-Datei,
Startprogramm und Rezept.

Das Fenster selbst, offscreen mit QtWebEngine gegen das echte
`hermes dashboard` (Sandbox von Chromium nur für den Test aus):

```sh
tests/dashboard-gui-check.py --launcher files/system/usr/libexec/hermes-os-dashboard \
  --dashboard-dir files/system/usr/share/hermes-os/dashboard --out /tmp/shots
```

Spielt durch: Warteseite, geladene Seite mit Hermes' Titel, Server von
außen beendet und „Neu laden" führt zur Fehlerseite, „Erneut versuchen"
startet ihn wieder, Beenden stoppt ihn; legt optional ein PNG je Zustand ab.
Exit 3 heißt, QtWebEngine läuft in dieser Umgebung nicht (Bindings fehlen,
Render-Prozess stirbt). Gelaufen am 2026-09-26 in der Cloud mit PySide6
6.11.2 aus PyPI und Hermes 0.21.5 aus einer lokal gebauten Venv: alle zehn
Schritte grün, die Seite zeigt Hermes' Seitenleiste (Chat, Sessions, Files,
Models, Logs, Cron, Skills, Plugins, MCP, Channels, Webhooks, Pairing,
Profiles, Config, Keys).

Das Gate (`80-validate.sh`, 7l) prüft im Image-Build außerdem: `web_dist`
mit Stempel aus demselben Release wie die Venv, `hermes-os-dashboard
--check` (PySide6-WebEngine, Modul, Frontend), `desktop-file-validate`,
`ujust --list`, startet das echte `hermes dashboard` aus der Venv
(`/api/health`, `index.html` mit Sitzungs-Token, ein Asset-Bundle, Stopp),
prüft, dass danach nichts Neues unter `/usr/lib/hermes-agent` liegt, und
fährt das Fenster offscreen (Exit 3 nur als WARN, weil Chromium in einem
Build-Container scheitern kann).

Frontend lokal bauen (ohne Podman, mit Node ab 22.22):

```sh
git clone --depth 1 --branch v2026.9.24 https://github.com/NousResearch/hermes-agent.git /tmp/hermes
cd /tmp/hermes && npm ci --workspace web && npm run build --workspace web
ls hermes_cli/web_dist/index.html hermes_cli/web_dist/assets
```

Messwerte vom 2026-09-26 mit Node 22.22.2, npm 10.9.7: `npm ci` 12 s
(454 Pakete), Build 21 s, `web_dist` 3,2 MB.

In der Test-VM aus dem Home starten, ohne neues Image:

```sh
systemd-run --user --unit hos-dash --collect -p ExitType=cgroup \
  -E HERMES_OS_DASHBOARD_DIR=/tmp/hos/share/hermes-os/dashboard -E HERMES_HOME=/tmp/hos/home \
  /usr/bin/python3 /tmp/hos/libexec/hermes-os-dashboard
```

Am 27.09. in VM 112 gelaufen: Fenster unter Wayland mit eigenem Scope auf
Port 9119, Schließen beendet den Scope
(`systemctl --user list-units 'hermes-os-dashboard-*'`), nach
`hermes dashboard --stop` von außen kommt die Fehlerseite erst beim Neuladen,
„Erneut versuchen“ startet den Server neu. Offen für VM 112: Sandbox von
Chromium unter Wayland ohne Sonderflags bestätigen, Menüpunkt am Symbol und
Knopf im Assistenten.

## Grenzen

- **Chat-Tab leer.** Er startet `hermes --tui` als Kindprozess, was Node und
  das TUI-Bundle braucht; beides ist nicht im Image. Fehlt Node, versucht
  Hermes es nach `~/.hermes` zu laden. Chat läuft über das Leisten-Symbol
  oder `hermes` im Terminal. Die TUI zu bauen wäre eine zweite Ausgabe
  derselben Node-Stufe (`ui-tui`), nicht entschieden.
- **Ein Server, mehrere Fenster.** Öffnet jemand das Fenster zweimal, zeigt
  das zweite den Server des ersten. Schließt das erste, nimmt es den Server
  mit, und das zweite landet beim nächsten Klick auf der Fehlerseite;
  „Erneut versuchen" startet ihn neu.
- **Port 9119 fest**, überschreibbar mit `HERMES_OS_DASHBOARD_PORT`.
- **Kein Icon fürs Dashboard**, es nimmt `hermes-os`.

## Stolperfallen

- `hermes dashboard --status` endet immer mit Exit 0; für „läuft es?" taugt
  nur `/api/health` (oder `hermes-os-dashboard --status`).
- Ohne `HERMES_WEB_DIST` und ohne `--skip-build` versucht Hermes auf jedem
  frischen Home einen npm-Build und bricht ohne npm mit Exit 1 ab.
- `QtWebEngineWidgets` vor `QApplication` importieren, sonst
  „AA_ShareOpenGLContexts must be set".
- Chromiums Sandbox braucht User-Namespaces; in einem Container-Test
  `QTWEBENGINE_DISABLE_SANDBOX=1` setzen, im Betrieb nicht.
- Die Page vor dem Profil freigeben (`view.setPage(None)`, `deleteLater`),
  sonst warnt Qt beim Beenden.
- Ein Timeout beim Start lässt den Server laufen; „Erneut versuchen" wartet
  dann weiter, statt einen zweiten zu starten (`Server.ensure` prüft
  `alive()`).
