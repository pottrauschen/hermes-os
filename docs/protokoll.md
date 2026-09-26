# Protokoll: was Hermes am System getan hat

Die Seite „Protokoll" im Chat-Fenster beantwortet ohne Terminal: Was hat
Hermes heute am System getan? Sie zeigt jede Freigabe-Anfrage mit
Entscheidung, jeden Terminal-Befehl mit Systemwirkung samt Ergebnis und jeden
App-Start über `app_launch`. Damit ersetzt sie den Punkt „unabhängiges
Audit-Log" aus Phase 4 in der Form, die ohne eigenen Dienst auskommt; siehe
[Grenzen](#grenzen).

## Was es tut

- **Seite „Protokoll"**, erreichbar über den Knopf mit der Uhr im Kopf des
  Chat-Fensters und den Menüpunkt am Symbol. Je Zeile: Zeit (mit Datum, wenn
  nicht von heute), Gruppe, Befehl, Entscheidung mit Entscheider und das
  Ergebnis mit Exit-Code; die gekürzte Ausgabe klappt auf. Das Symbol links
  zeigt das Ergebnis: ausgeführt, mit Fehler beendet, nicht ausgeführt,
  wartet, App gestartet. Escape oder der Pfeil führen zurück zum Chat.
- **Filter**: Zeitraum heute, letzte 7 Tage oder alles; Häkchen „Nur
  Änderungen" zeigt nur Systembefehle, die wirklich gelaufen sind (erfolgreich
  oder mit Fehler). Abgelehnte, verweigerte und offene Anfragen und App-Starts
  fallen dabei weg.
- **Export**: „Exportieren" schreibt die gezeigten Zeilen über den
  Dateidialog als Textdatei, älteste zuerst, mit Kopf (Rechner, Zeitpunkt,
  Filter).
- **Aktualisierung**: Solange die Seite offen ist, liest das Symbol die Datei
  bei jeder Änderung neu (`QFileSystemWatcher` auf Datei und Ordner, 0,5 s
  gebündelt). Bei geschlossener Seite merkt es sich nur, dass etwas kam.

## Wer schreibt was

Ablage ist `$XDG_STATE_HOME/hermes-os/audit.jsonl` (Vorgabe
`~/.local/state/hermes-os/audit.jsonl`), Datei 0600, Ordner 0700. Eine
JSON-Zeile je Ereignis, nur angehängt. Ab 5 MB wird die Datei zu
`audit.jsonl.1`, eine ältere Vorgängerdatei verfällt. Beide Seiten nutzen
`plugins/hermes_os/audit.py`; das Symbol lädt das Modul wie `library.py` über
seinen Dateipfad, es braucht weder Hermes noch Qt.

| Ereignis | Wer | Hook oder Stelle | Inhalt |
|---|---|---|---|
| `approval.request` | Plugin | `pre_approval_request` | Befehl, Beschreibung, `pattern_key`, Oberfläche (cli, gateway, smart) |
| `approval.decision` | Plugin | `post_approval_response` | dazu `choice` und `decided_by` |
| `command.result` | Plugin | `post_tool_call` für `terminal` | Status (ok, error, blocked), Exit-Code, gekürzte Ausgabe, Fehler, Dauer |
| `app.launch` | Plugin | `post_tool_call` für `app_launch` | App-ID, Ziel, Ergebnistext |
| `tray.decision` | Leisten-Symbol | Klick auf Karte oder Benachrichtigung | angezeigter Befehl, Wahl, `request_id` |

Alle Ereignisse eines Werkzeugaufrufs tragen dieselbe `call`
(`tool_call_id`) und werden beim Lesen zu einer Zeile. Ein Klick im Symbol
kennt diese Kennung nicht; er hängt sich an die jüngste Anfrage mit demselben
angezeigten Befehl aus der letzten Stunde und fügt „im Leisten-Symbol" an.

Ein Ergebnis schreibt das Plugin nur für Terminal-Befehle, die der
Freigabe-Hook als Systembefehl erkannt hat (`classify_system_command`, dieselben
Gruppen wie in der Grenze) oder die durch den Freigabe-Dialog gingen (Hermes'
eigener Detektor, etwa `rm -r`). Freie Befehle im Home landen nicht im
Protokoll. Der `pre_tool_call`-Hook merkt sich den Treffer nur im Speicher;
geschrieben wird erst mit der Anfrage oder dem Ergebnis, damit Trockenläufe
(Gate, `venv-smoke.sh`) keine Datei anlegen.

Im `__init__.py` stehen dafür zwei Zeilen: `audit.record_flagged` im Hook und
`audit.register_hooks` in `register()`. Alles andere liegt in `audit.py`.

## Entscheidung und Entscheider

| Anzeige | Woher |
|---|---|
| Einmal erlaubt, Für die Sitzung erlaubt, Immer erlaubt, Abgelehnt (Nutzer) | `choice` once, session, always, deny |
| Vom Guardian erlaubt oder abgelehnt (Guardian) | `choice` smart_approve, smart_deny, `decided_by` aux_llm |
| Zeitüberschreitung, Zurückgezogen, Nicht zustellbar (keine Antwort) | `choice` timeout, cancelled, notify_failed |
| Verweigert (Cron-Verweigerung) | Ergebnis `blocked` mit dem Cron-Text aus `approvals.cron_mode: deny`; in Cron feuert kein Freigabe-Hook |
| Verweigert (niemand erreichbar) | Ergebnis `blocked` ohne Mensch und ohne Gateway |
| Ohne Rückfrage (gespeicherte Freigabe) | Ergebnis ohne Freigabe-Hook: vorher „für diese Sitzung" oder „immer" erlaubt, oder Freigaben aus (`approvals.mode: off`, yolo) |

Fragen Plugin und Hermes' eigener Detektor nacheinander für denselben Aufruf
(so bei `systemctl restart` in 0.21.5), bleibt es eine Zeile; die letzte
Entscheidung zählt.

## Hook-Vertrag in Hermes 0.21.5

Nachgelesen im Tag `v2026.9.24`:

- `hermes_cli/plugins.py`, `VALID_HOOKS`: neben `pre_tool_call` gibt es
  `post_tool_call` sowie die Beobachter `pre_approval_request` und
  `post_approval_response`. Beobachter können nichts verhindern, ihre
  Rückgabe wird ignoriert.
- `model_tools._emit_post_tool_call_hook`: `tool_name`, `args`, `result`,
  `task_id`, `session_id`, `tool_call_id`, `turn_id`, `api_request_id`,
  `duration_ms`, `status` (ok, error, blocked), `error_type`,
  `error_message`. Auch ein vom `pre_tool_call`-Hook blockierter Aufruf
  bekommt `post_tool_call` mit `status="blocked"` und der Blockier-Meldung.
  `post_tool_call` läuft mit `plugins.hook_callback_timeout`.
- `tools/approval_gateway_wait.py`, `tools/approval.py`,
  `tools/approval_smart.py`: die Freigabe-Hooks bekommen `command`,
  `description`, `pattern_key`, `pattern_keys`, `session_key`, `surface`,
  über den Kontext auch `tool_call_id`, `turn_id`, `session_id`;
  `post_approval_response` dazu `choice` und beim Guardian `decided_by`.
  Bei einer Plugin-Freigabe ist `command` der Platzhalter
  `<terminal> (plugin approval rule)` und `pattern_key`
  `plugin_rule:hermes-os:<gruppe>`; den echten Befehl kennt das Protokoll aus
  dem Treffer des eigenen Hooks.
- Terminal-Ergebnis ist JSON mit `output`, `exit_code`, `error`.

## Grenzen

- **Das Protokoll ist nicht unabhängig.** Es liegt im Home und wird vom
  Prozess geschrieben, den es beobachtet. Wer als Nutzer oder als Agent
  Schreibrecht im Home hat, kann es ändern. Ein manipulationsfestes Log
  (eigener Dienst, eigener Nutzer, Journal mit Siegel) bleibt Teil von
  Phase 4.
- **Nur was durch Hermes' Hooks geht.** `execute_code`, Datei-Werkzeuge
  (`write_file`, `patch`) und MCP-Werkzeuge stehen nicht im Protokoll, ebenso
  Befehle, die der Nutzer selbst im Terminal tippt.
- **Ausgabe gekürzt und geschwärzt.** 800 Zeichen, Anfang und Ende;
  offensichtliche Geheimnisse (`password=`, `token`, `Bearer`, `sk-…`,
  Zugangsdaten in Adressen) werden durch `***` ersetzt. Das ist eine
  Heuristik, keine Garantie.
- **Mehrere Profile**: Jeder Hermes-Prozess des Nutzers schreibt in dieselbe
  Datei, ob Gateway oder Terminal-Chat. Das ist gewollt; die Oberfläche steht
  nicht in der Zeile, nur im Ereignis (`surface`).

## Testen

```sh
python3 tests/audit-check.py --plugin-dir files/system/usr/share/hermes-os/plugins/hermes_os
```

Ohne Qt und ohne Hermes: Freigabe mit Klick und Ergebnis, zwei Anfragen für
einen Aufruf, Ablehnung, Guardian, Zeitüberschreitung, Cron-Verweigerung,
gespeicherte Freigabe, Rückfall über `classify`, freie Befehle, `app_launch`,
Dateirechte, kaputte Zeilen, Filter, Export, Schwärzen, Kürzen, Rotation.
`make lint` und das Gate (`80-validate.sh`, 7h) führen ihn aus. Schritt 6 des
Gates lädt das Plugin über den echten Loader, prüft, dass die drei Hooks
hängen, und schickt ein `post_tool_call` durch Hermes' `invoke_hook` bis in
die Datei. `tests/tray-gui-check.py` rendert die Seite offscreen: öffnen,
Symbole, Ausgabe aufklappen, Zeitraum, nur Änderungen, Export, leer, Menü,
Wechsel zur Bibliothek.

## Stolperfallen

- **Das Häkchen „Nur Änderungen" zählt auch fehlgeschlagene Befehle.** Ein
  `systemctl restart` mit Exit 5 kann trotzdem etwas verändert haben.
- **Offene Anfragen ohne Ergebnis** bleiben „wartet", wenn das Gateway
  zwischen Anfrage und Antwort beendet wurde.
- **PySide6 verlangt für QML-Funktionen alle Parameter**, deshalb
  `auditSetFilter(period, changesOnly)` immer mit beiden.
- **Der Watcher verliert die Datei bei der Rotation**; das Symbol hängt sie
  nach jeder Änderung am Ordner wieder an.
