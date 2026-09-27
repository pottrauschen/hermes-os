# Lokales Modell: Hermes ohne Cloud auf der eigenen GPU (optional)

Stand: 2026-09-27. Wie Hermes auf hermes-os mit einem Modell läuft, das auf
dem Rechner selbst rechnet, was dafür im Image liegt und was erst auf Wunsch
nachgeladen wird, warum es so gebaut ist und wo die Grenzen sind.

## Entscheidung: optional, Ollama nicht im Image

Das lokale Modell ist eine Option, kein Bestandteil. Ollama selbst liegt
seit 2026-09-27 nicht mehr im Image; wer es will, lädt es mit
`ujust hermes-lokal-ein` oder der Karte im Assistenten in sein Home. Gründe:

- **Kleine Modelle bringen wenig.** Was auf eine 12-GB-Karte passt, bleibt
  bei Werkzeugaufrufen deutlich hinter den Cloud-Modellen zurück (in VM 112
  verfehlte `qwen3.5:4b` das Meta-Werkzeug `tool_call` und wich auf die
  Websuche aus). Das rechtfertigt nicht, jedes Image damit zu belasten.
- **Rund 0,9 GB weniger in beiden Images** (`/usr/lib/ollama`, davon
  0,85 GB CUDA 13) und kein Bump des Images für einen Ollama-Bump.
- **Die CUDA-Laufzeit liegt nicht mehr im Image.** Das Ollama-Archiv
  enthält cuBLAS und cudart; im Image verteilte hermes-os sie mit. Jetzt
  kommt das Archiv auf Wunsch direkt von Ollamas Releases auf den Rechner.
  Ob NVIDIAs Weitergabe-Bedingungen damit ganz erledigt sind, ist nicht
  geprüft; das Image selbst enthält nichts mehr davon.

Was im Image bleibt: der Nutzerdienst `ollama.service` (zeigt auf das
Programm im Home und bleibt ohne es still aus), der Helfer
`hermes-os-lokal`, das Modul `local_model.py`, die Rezepte, die Karte im
Assistenten, `zstd` zum Entpacken. Alle übrigen Funktionen von hermes-os
hängen nicht am lokalen Modell.

**Nachladen, gepinnt wie früher im Build.** `local_model.install_ollama`
lädt `ollama-linux-amd64.tar.zst` in der Version `OLLAMA_PIN` von
`github.com/ollama/ollama/releases`, vergleicht die SHA256 mit
`OLLAMA_SHA256` (aus der `sha256sum.txt` des Releases übernommen), entpackt
ohne `cuda_v12` nach `~/.local/share/hermes-os/ollama/{bin,lib}` und schreibt
den Stempel `.hermes-os-release` (Version, Prüfsumme, Backends). Vorher prüft
es den Platz: Archiv (1,3 GB) und Ergebnis (0,9 GB) liegen beim Entpacken
nebeneinander, dazu 1 GB Luft. Erst nach Prüfsumme, Entpacken und einem
Probelauf (`ollama --version`) ersetzt es ein vorhandenes Ollama; scheitert
ein Schritt, bleibt der alte Stand.

## Warum Ollama, und warum als Nutzerdienst

**Ollama statt llama-server.** Beide bringen einen OpenAI-kompatiblen
Endpunkt mit Werkzeugaufrufen, den Hermes als Anbieter `custom` anspricht.
Der Unterschied liegt im Drumherum: Ollama lädt Modelle aus seiner
Bibliothek mit Fortschritt (`/api/pull`), verwaltet sie (`/api/tags`,
`/api/show` mit Fähigkeiten wie `tools` und Kontextlänge), wählt beim Start
selbst das Rechen-Backend (CUDA, Vulkan, CPU) und hält ein Modell nach
Gebrauch im Speicher. Der Assistent und die ujust-Rezepte brauchen genau
das. llama-server (ggml-org/llama.cpp, Release b11205) kann Werkzeugaufrufe
inzwischen ohne Zusatzflag (`--jinja` ist Standard) und holt GGUF-Dateien
per `-hf` von Hugging Face, hat aber weder Pull mit Fortschritt noch eine
Modellverwaltung noch die automatische Wahl des Backends; die CUDA-Builds
gibt es nur für Ubuntu, und ob sie auf Fedora laufen, ist ungeprüft. Ollama
bündelt llama.cpp ohnehin (`lib/ollama/llama-server` liegt bei). Hermes
kennt für llama-server den Slug `llamacpp`, der aber Hermes' eigene
Laufzeit meint und `model.base_url` ignoriert; ein fremder llama-server wäre
ebenfalls `custom`. Das bleibt als Ausweg offen, braucht aber keinen Code.

**Das native Archiv statt Podman-Quadlet.** Der Release-Tarball
`ollama-linux-amd64.tar.zst` (v0.34.4 vom 2026-09-23, 1,3 GB, entpackt
2,2 GB, Layout geprüft) enthält `bin/ollama` und `lib/ollama` mit
CPU-Backends je Prozessorfamilie, CUDA 12 (1,3 GB), CUDA 13 (0,85 GB) und
Vulkan (43 MB). cuBLAS und cudart liefert Ollama selbst mit; vom Host
braucht es nur `libcuda.so.1` aus dem Treiber. Gründe gegen den Container:

- Ein Quadlet müsste `docker.io/ollama/ollama` (3,75 GB komprimiert) ins
  Home ziehen, mit `latest` oder einem Pin, den niemand mit dem Image
  aktualisiert. Das Archiv ist kleiner und in `local_model.py` gepinnt: eine
  Version, ein Bump, geprüft mit SHA256.
- GPU im Container braucht CDI. `aurora-dx-nvidia-open` bringt
  `nvidia-container-toolkit` und `nvidia-cdi-refresh.service` mit (die Datei
  liegt unter `/var/run/cdi/nvidia.yaml`), die AMD/Intel-Variante nichts
  davon; das Quadlet wäre je Variante anders. Universal Blue hatte
  `ujust ollama` als Quadlet und hat es am 2024-11-21 wieder entfernt
  (Bluefin-Commit `c271947`); heute empfiehlt Aurora ramalama per Homebrew.
- Der Agent auf dem Host sieht den Container nicht: `ollama ps`, Logs und
  Modelle lägen hinter `podman exec`.

**Ein Archiv für beide Varianten.** Nichts fragt beim Nachladen nach der
GPU. Ollama prüft beim Start jedes Backend-Verzeichnis neben dem Programm
(`~/.local/share/hermes-os/ollama/lib/ollama`): CUDA über den NVIDIA-Treiber
(nur im NVIDIA-Image vorhanden), Vulkan über Mesa (AMD, Intel) oder als
Ausweich über den NVIDIA-Treiber, sonst CPU mit dem Log
`inference compute id=cpu`. Die AMD/Intel-Variante rechnet also mit einer
AMD- oder Intel-GPU über Vulkan und ohne GPU auf der CPU; der Helfer sagt
vorher, was er vorfindet. `cuda_v12` wird nicht entpackt: die offenen
Kernelmodule laufen erst ab Turing, das deckt CUDA 13 (Treiber ab 580; Aurora
stable hat 615.71.09) ab. Spart 1,3 GB im Home; das Programm ist rund 0,9 GB
groß. ROCm-Bibliotheken kommen nicht mit (eigener Tarball, 1 GB); AMD läuft
über Vulkan.

**Nutzerdienst statt Systemdienst.** `ollama.service` liegt unter
`/usr/lib/systemd/user`, ist ab Werk aus und hört nur auf `127.0.0.1:11434`.
Er startet `%h/.local/share/hermes-os/ollama/bin/ollama` und hat dieselbe
Datei als `ConditionPathExists`: ohne nachgeladenes Programm bleibt er still
aus, statt in eine Neustartschleife zu laufen.
Modelle liegen unter `~/.local/share/ollama/models` (`OLLAMA_MODELS`), nicht
unter `/var/lib` und nicht im versteckten `~/.ollama`; ein Image-Update
lässt sie in Ruhe. Das hält alles in der Grenze: `systemctl --user` und das
Home sind frei, der Agent darf den Dienst ohne Rückfrage schalten
(`docs/grenze.md`), und niemand braucht Root. Ollamas eigenes `install.sh`
täte das Gegenteil (System-Unit, Nutzer `ollama`, Treiber per dnf) und ist
auf bootc unbrauchbar.

## Was im Image liegt und was nachgeladen wird

| Was | Wo |
|---|---|
| Pin `OLLAMA_PIN`, Archiv, `OLLAMA_SHA256`, Nachladen, Platzprüfung, Entfernen | `files/system/usr/share/hermes-os/local/local_model.py` |
| Ollama, Backends, Stempel (nachgeladen, nicht im Image) | `~/.local/share/hermes-os/ollama/bin/ollama`, `…/lib/ollama/{cuda_v13,vulkan,…}`, `…/.hermes-os-release` |
| Modelle (nachgeladen) | `~/.local/share/ollama/models` |
| Nutzerdienst | `files/system/usr/lib/systemd/user/ollama.service` |
| Logik: GPU, Ollama-API, Vorschläge, Config-Schreibweg | `files/system/usr/share/hermes-os/local/local_model.py` |
| Helfer für Rezepte, Assistent und Agent | `files/system/usr/libexec/hermes-os-lokal` |
| Rezepte | `hermes-lokal-ein`, `-aus`, `-entfernen`, `-modell`, `-status` in `hermes-os.just` |
| Karte im Assistenten | `setup/Main.qml` (Seite „Lokales Modell“), Backend in `hermes-os-setup` |
| Anleitung für den Agenten | Abschnitt „Lokales Modell statt Cloud“ in `skills/hermes-os-system/SKILL.md` |
| `zstd` fürs Entpacken, PyYAML für den Helfer | `files/scripts/20-agent-layer.sh` |
| Test | `tests/lokales-modell-check.py`, Gate `80-validate.sh` Abschnitt 7m, „kein Ollama im Image“ in `89-tests.sh` |

## Wie Hermes angebunden ist

Hermes 0.21.x (Tag v2026.9.24) hat keinen eigenen Ollama-Slug; `ollama` ist
ein Alias auf `custom`, den Anbieter für OpenAI-kompatible Server. Der Helfer
schreibt in `~/.hermes/config.yaml` denselben Block, den Hermes' Wizard für
einen Custom-Endpunkt ohne Schlüssel erzeugt (`_persist_model`), plus drei
Einträge, die ein Agent mit Werkzeugen an Ollama braucht:

```yaml
model:
  default: qwen3.5:9b
  provider: custom
  base_url: http://127.0.0.1:11434/v1
  api_mode: chat_completions
  context_length: 65536      # deckelt, was Hermes aus /api/show liest (GGUF sagt 256k)
  ollama_num_ctx: 65536      # hebt über Hermes' Untergrenze, auch wenn das Modell weniger meldet
agent:
  reasoning_effort: none     # Hermes schickt dann think:false an Ollama
```

Es entsteht keine `.env`-Zeile: ohne Schlüssel setzt Hermes selbst
`no-key-required` als Bearer, und Ollama prüft keinen. Der Schlüssel für den
API-Server des Gateways (Leisten-Symbol) kommt trotzdem in `.env`, weil der
Helfer nach dem Eintragen das First-Login-Skript ruft; das erkennt seit
diesem Stand auch einen Anbieter in `config.yaml` als Einrichtung. Das
Gateway liest `config.yaml` bei jedem Gesprächsschritt neu und baut den
Agenten um, sobald Modell, Adresse oder Anbieter wechseln; ein Neustart ist
nicht nötig. Sitzungen mit eigenem `/model` bleiben auf ihrem Modell.

Warum nicht Hermes' `_persist_model` über die Brücke des Assistenten: der
Schreibweg muss auch aus dem ujust-Rezept mit Fedoras Python laufen und im
Test ohne Hermes prüfbar sein. Der Vertrag ist stattdessen im Gate: was
`hermes-os-lokal eintragen` schreibt, liest `hermes config get` zurück, und
65536 liegt über `MINIMUM_CONTEXT_LENGTH`. Der Katalog der Brücke blendet
`custom` ohnehin aus (kein Schlüssel), deshalb kommt die Karte aus dem
Assistenten selbst, sobald `/usr/libexec/hermes-os-lokal` da ist.

**64k Kontext ist Pflicht.** Hermes verweigert den Start mit Werkzeugen
unter 64.000 Token (`agent/agent_init.py`, Meldung verweist auf
`OLLAMA_CONTEXT_LENGTH` oder `model.ollama_num_ctx`). Ollama gibt Karten
unter 23 GiB nur 4096 Token, und der OpenAI-kompatible Endpunkt nimmt
`num_ctx` nicht je Anfrage an (Hermes schickt es in `extra_body.options`,
Ollama ignoriert es dort). Deshalb setzt die Unit `OLLAMA_CONTEXT_LENGTH=65536`
für alle Modelle, dazu `OLLAMA_FLASH_ATTENTION=1` und
`OLLAMA_KV_CACHE_TYPE=q8_0` (halbiert den Cache), `OLLAMA_KEEP_ALIVE=1h`
und `OLLAMA_NO_CLOUD=1`. Wer mehr will, überschreibt mit
`systemctl --user edit ollama.service`.

**Werkzeugaufrufe.** Hermes schickt an `custom` nur `tools` (kein
`tool_choice`, kein `parallel_tool_calls`, kein `max_tokens`) und erwartet
echte `tool_calls` in der Antwort; einen Text-Fallback gibt es nicht. Das
Modell muss die Fähigkeit `tools` haben (Ollama-Bibliothek, Filter „tools“).
Die Prüfung im Helfer und im Assistenten schickt genau so eine Anfrage mit
einer Werkzeugdefinition und lässt nur eintragen, was mit einem Aufruf
antwortet. Denkmodus: ohne Einstellung schickt Hermes an Custom-Endpunkte
`reasoning_effort: medium`, Qwen3.5 dächte dann vor jedem Werkzeugschritt;
`agent.reasoning_effort: none` wird zu `think: false` (nur auf Port 11434)
und verhindert auch Werkzeugaufrufe im Denkblock, ein bekanntes
Qwen3.5-Problem. Der Helfer merkt sich den vorherigen Wert und stellt ihn
mit `aus` zurück. Ollamas `/v1`-Endpunkt setzt `temperature 1.0`, wenn der
Client keine schickt; Hermes schickt keine. Das ist nicht ideal für
Werkzeugaufrufe und in der VM zu beobachten.

## Modellwahl für 12 GB

Empfehlung nach der Recherche vom 2026-09-26 (Ollama-Bibliothek, Ollamas
eigene Hermes-Anleitung `docs/integrations/hermes.mdx`, `cmd/launch/models.go`,
Hermes' `local-ollama-setup.md`, Speicherrechnung nach Architektur). Die
Downloadgrößen stammen aus Suchauszügen, `ollama.com` war aus der Cloud
nicht erreichbar; die VRAM-Werte sind gerechnet, nicht gemessen.

| Modell | Größe | 64k in 12 GB | Warum |
|---|---|---|---|
| **`qwen3.5:9b`** (Vorgabe) | 6,6 GB | ja, rund 8,5 GB mit q8_0-Cache | Werkzeugaufrufe verlässlich (Familie führt den Tool-Calling-Test von jdhodges an), 201 Sprachen, 256k Modellkontext, hybrid: nur 8 von 32 Schichten haben einen KV-Cache (32 KiB je Token statt 160 KiB bei `qwen3:14b`). Ollama nennt es selbst als lokales Modell für Hermes. |
| `qwen3.5:4b` (8 GB, CPU) | 3,4 GB | ja, deutlich | Gleiche Familie; für 8-GB-Karten und ohne GPU. Auf der CPU dauert das erste Verarbeiten von Systemprompt und Werkzeugschemas Minuten. |
| `gemma4:12b` | 7,6 GB | vermutlich | Besseres Deutsch im Praxistest; Werkzeugaufrufe im September 2026 noch mit offenen Fehlern (Hermes #79639 verliert mit `tools` den Verlauf, Ollama #18275 kaputtes Aufrufformat). Testkandidat. |
| `granite4:tiny-h` | 4,2 GB | ja | IBM, Deutsch offiziell, Mamba-Hybrid ohne Denkmodus. Schlichter. |

Ausgeschieden: `qwen3:14b` und `qwen3:8b` (dichte Modelle; 64k Kontext
braucht 5 bis 10 GiB Cache, dazu 40k Kontextgrenze), `gpt-oss:20b` (14 GB,
Denken nicht abschaltbar, vorwiegend englisch), `gemma3` und
`deepseek-r1:14b` (keine Werkzeuge in Ollama), `mistral-small3.2`,
`devstral-small-2`, `glm-4.7-flash`, `qwen3.6:27b`, `gemma4:31b` (15 bis
20 GB). Ein Hermes-4-Modell von Nous liegt nicht in der Ollama-Bibliothek.

Die Vorgabe wählt `recommend()` in `local_model.py` nach dem Speicher der
Karte: 12 GB `qwen3.5:9b`, 8 GB `qwen3.5:4b`, ohne GPU `qwen3.5:4b`. Der
Nutzer kann im Assistenten und im Rezept jedes andere Ollama-Tag angeben;
die Prüfung auf Werkzeugaufrufe bleibt.

## Bedienung

Im Assistenten (`ujust hermes-setup`, Menü „Hermes einrichten“): Anbieter
„Lokales Modell (Ollama)“, dann auf einer Seite Ollama laden (nur beim
ersten Mal, mit Fortschritt und Platzangabe), Dienst starten, Modell wählen
und laden (Fortschritt; Modelle, die nicht auf die Platte passen, sind
markiert), Verbindung prüfen, eintragen. Im Terminal oder durch den Agenten:

```sh
ujust hermes-lokal-status              # GPU, Ollama, Dienst, Modelle, was Hermes nutzt
ujust hermes-lokal-ein                 # Ollama laden (falls nötig), Dienst an, Vorgabe laden, prüfen, eintragen
ujust hermes-lokal-ein qwen3.5:4b      # mit eigenem Modell
ujust hermes-lokal-modell gemma4:12b   # anderes Modell laden, prüfen, eintragen
ujust hermes-lokal-aus                 # Dienst aus, vorheriger Anbieter zurück
ujust hermes-lokal-entfernen           # wie aus, dazu Ollama und alle Modelle löschen
```

Vor jedem Modell-Download prüft der Helfer den Platz unter
`~/.local/share/ollama`: bekannte Modelle mit ihrer Größe plus 1 GB Luft,
eigene Tags mit einer Untergrenze von 2 GB und einem Hinweis, dass die Größe
unbekannt ist. Reicht es nicht, bricht er vorher ab.

`aus` holt den model-Block und `agent.reasoning_effort` von vor dem
Umschalten zurück (`~/.hermes/hermes-os/local-previous-model.json`). War
vorher kein Anbieter eingetragen, ist Hermes danach ohne Modell und der
Assistent oder `hermes setup` wählt neu. Für den Agenten ist das Umschalten
frei (Nutzerdienst, Home, `ujust hermes-*`), aber nur auf ausdrücklichen
Wunsch; der Skill sagt ihm, was er vorher ankündigt.

## Testen

Ohne GPU, ohne Ollama, ohne Hermes:

```sh
tests/lokales-modell-check.py --local-dir files/system/usr/share/hermes-os/local
```

Prüft die GPU-Erkennung gegen Attrappen (ein `nvidia-smi` im PATH, das eine
RTX 3060 meldet; eines, das scheitert; ein `/dev/kfd`; nichts), die
Vorschläge, den Config-Schreibweg gegen eine Wegwerf-`config.yaml` aus der
Vorlage (Block, Rest, 0600, Merken und Zurückholen), die Endpunktprüfung
gegen einen nachgebauten Ollama-Server (`/api/version`, `/api/tags`,
`/api/show`, `/api/pull` als Strom, `/v1/models`, `/v1/chat/completions`
mit und ohne Werkzeugaufruf) und das Nachladen gegen ein nachgebautes
Release-Archiv über `file://` (falsche Prüfsumme, richtige ohne `cuda_v12`,
zu wenig Platz, zweiter Aufruf, Entfernen; braucht `tar` und `zstd`), dazu
den Helfer mit einem `systemctl`, das nur mitschreibt. Kein Schritt geht ins
Internet. `make lint` und das Gate (`80-validate.sh` 7m) führen ihn aus; das
Gate prüft außerdem, dass kein Ollama im Image liegt, die Unit, die Rezepte
und den Vertrag mit Hermes.

Nur in Test-VM 112 (RTX 3060 per Passthrough, `docs/testumgebung.md`) lässt
sich prüfen, was die Cloud nicht kann. Am 2026-09-27 (noch mit Ollama im
Image) bestanden: `inference compute … library=CUDA`, `qwen3.5:4b` mit
100 % GPU und Kontext 65536, `os_services` über das lokale Modell, Bilder im
Chat, `hermes-lokal-aus` mit Rückkehr zum Cloud-Anbieter. Die Vorgabe
`qwen3.5:9b` passte nicht auf die 31-GB-Platte der VM (6,1 GB frei); daher
die Platzprüfung.

```sh
ujust hermes-lokal-ein                              # Ollama laden, Dienst, Download 6,6 GB, Prüfung, Eintrag
journalctl --user -u ollama.service -n 40           # "inference compute" muss CUDA nennen
ollama ps                                           # 100 % GPU, Kontext 65536, Größe im VRAM
nvidia-smi --query-gpu=memory.used --format=csv     # Luft neben Plasma (rund 0,5 bis 1 GB)
hermes                                              # Chat: "Welche Dienste sind fehlgeschlagen?" muss os_services aufrufen
ujust hermes-lokal-aus                              # Anbieter zurück
ujust hermes-lokal-entfernen                        # Programm und Modelle weg, Platz zurück
```

Zeigt `ollama ps` weniger als 100 % GPU, ist der Kontext für die Karte zu
groß: `OLLAMA_CONTEXT_LENGTH=65536` beibehalten und `qwen3.5:4b` nehmen,
nicht den Kontext senken (Hermes startet dann nicht).

## Grenzen und Stolperfallen

- **Ollama meldet Vulkan auch für NVIDIA.** Findet es CUDA, gewinnt CUDA;
  ohne `libcuda.so.1` (AMD/Intel-Image auf NVIDIA-Hardware mit Nouveau) läuft
  es über Vulkan und ist langsamer. `journalctl --user -u ollama.service`
  zeigt beim Start, welches Backend es nimmt.
- **Ohne GPU ist es langsam.** Ein 4B-Modell auf der CPU antwortet, aber der
  erste Schritt mit Werkzeugschemas dauert Minuten. Der Helfer sagt das
  vorher; `HERMES_API_TIMEOUT` in `.env` verlängert Hermes' Geduld.
- **`hermes doctor`** meldet bei `custom` ohne Schlüssel fälschlich „No API
  key found in .env“. Der Endpunkt braucht keinen.
- **Modellliste im Assistenten** kommt aus `local_model.RECOMMENDED`; wer ein
  fremdes Tag einträgt, bekommt keine Speicherwarnung, nur die
  Werkzeugprüfung und die Platz-Untergrenze.
- **Speicher:** Ollama selbst braucht rund 0,9 GB, `~/.local/share/ollama`
  wächst je Modell um 3 bis 8 GB. `ollama rm <tag>` räumt ein Modell auf; das
  Rezept `aus` löscht nichts, `entfernen` alles.
- **Umstieg von einem Image mit Ollama darin:** Das alte `/usr/bin/ollama`
  verschwindet mit dem Image-Update, die Modelle unter `~/.local/share/ollama`
  bleiben. `ollama.service` bleibt aus, bis `ujust hermes-lokal-ein` das
  Programm ins Home geladen hat; danach findet es die Modelle wieder.
- **Bump:** `OLLAMA_PIN` und `OLLAMA_SHA256` in `local_model.py` (Wert aus der
  `sha256sum.txt` des Releases), danach in VM 112 die Schritte oben. Ein neuer
  Tarball kann Backend-Verzeichnisse umbenennen; der Stempel
  `~/.local/share/hermes-os/ollama/.hermes-os-release` zeigt, welche Backends
  mitkamen.
