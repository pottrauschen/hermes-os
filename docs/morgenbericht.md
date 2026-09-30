# Morning report

Once a day Hermes reports on its own with a desktop notification. The report
text is German only for now; translated, it reads for example:

> **Morning report**
> New image available (44.20260926). 3 errors in the journal since yesterday 08:30,
> 1 of them new: bluetooth.service. /home at 92 %. No failed service.
> 2 Flatpak updates available.
> [Discuss in chat]

The button (German label: „Im Chat besprechen“) opens the Kontor (the chat
window) of the tray icon with the whole report as context. The report never
starts an update by itself; anyone who writes “install the update” in the chat
gets the usual approval from the boundary (README).

## Turning it on and off

```sh
ujust hermes-morgenbericht-ein          # asks for the time, default 08:30
ujust hermes-morgenbericht-ein 07:45    # no prompt; this is how the agent sets it up too
ujust hermes-morgenbericht-aus
/usr/libexec/hermes-os-morgenbericht --probe   # show the report now without saving it
```

The agent knows the recipes from the skill `hermes-os-system` and sets up the
report when asked; `ujust hermes-morgenbericht-*` runs freely, the approval
hook only applies to `ujust update` and its relatives. Without a running
gateway no report arrives; the recipe points this out.

## What it contains

| Part | Source | In the report |
|---|---|---|
| Update status | `tools.image_update_state()`, the same logic as `os_updates`: `rpm-ostree status --json` and `skopeo inspect` (digest and label `org.opencontainers.image.version`) | available, ready after a reboot, up to date or unknown |
| Journal errors | `journalctl --since @<last report> -p err -o json`, counted by unit (user units instead of `user@`), otherwise by `SYSLOG_IDENTIFIER` | the count, and which sources did not appear in the last report |
| Disk space | `df -B1 --output=…` for `/`, `/var`, `/home`; on bootc `/` is a composefs image, so `/sysroot` is measured instead; paths on the same file system are merged | from 85 % “at N %” („bei N %“), from 95 % “nearly full” („fast voll“), otherwise “ok (at most N %)” („ok (höchstens N %)“) |
| Services | `systemctl list-units --failed`, system and `--user` | names of the failed units |
| Flatpak | `flatpak remote-ls --updates` (like `os_updates`), can be turned off with `flatpak=false` | only when updates are pending |

The summary is the notification. The details (sources with their count and a
sample line, usage per file system, image lines) go into the chat as context.
If a command is unavailable (for example without access to the system journal,
or without network for skopeo), the sentence says “unknown” („unbekannt“) or
“not readable” („nicht lesbar“), and the report still arrives. If the account
cannot see the system journal (not in wheel, adm or systemd-journal), the note
“(only own entries readable)” („(nur eigene Einträge lesbar)“) is added.

## How it is built

```
Gateway (hermes-gateway.service, cron ticker every 60 s)
  └─ job hermes-os-morgenbericht, "30 8 * * *", --script, --no-agent, deliver local
       └─ ~/.hermes/scripts/hermes-os-morgenbericht.sh   (created by the recipe, only hands over)
            └─ /usr/libexec/hermes-os-morgenbericht      (Fedora's Python)
                 ├─ report.build_report(record=True)     → $XDG_STATE_HOME/hermes-os/morgenbericht.json
                 └─ report.handle_desktop_notify(report=True)
                      └─ systemd-run --user --collect --unit hermes-os-notify-XXXX
                           └─ sh: notify-send -A chat=… -A default=… waits for the choice
                                └─ chat or click: hermes-os-tray --discuss <context-file>
                                     └─ local socket to the running instance, otherwise a new instance
```

- **Script job without a model.** Besides tasks for the agent, Hermes' cron
  knows script jobs (`hermes cron create … --script … --no-agent`): Hermes runs
  the script and stores its output under `~/.hermes/cron/output/<job>/`; no
  model runs. So the report costs nothing, needs no reachable provider and
  cannot change anything; the agent only joins in the chat.
  `deliver local` sends nothing to messaging platforms.
- **The same tools as in the chat.** `os_report` and `desktop_notify` live in
  `plugins/hermes_os/report.py` and are registered for the agent; the entry
  point loads the same file. If you ask “how is the system doing?” in the chat,
  the agent can call `os_report` without moving the point of comparison
  (`record` is only set in the daily run).
- **State** under `$XDG_STATE_HOME/hermes-os/` (default `~/.local/state`):
  `morgenbericht.json` with `baseline` (time and sources of the last daily
  report) and `latest` (the last report, for `desktop_notify`), and
  `notify/*.txt` with the notifications' context files, kept for 14 days. The
  first report looks back 24 hours and does not flag anything as new yet.
- **The button takes the tray icon's path.** As with approvals,
  `notify-send --action` waits and writes the choice to stdout. The way into
  the window is the same local socket through which the menu and Meta+H send
  `--show`; the new part is the command `discuss <path>`. The icon only reads
  files from `$XDG_STATE_HOME/hermes-os/notify/`
  (`hermes_client.read_context_file`), shows the report as a bubble from
  Hermes and puts it in front of the next message as context, marked as
  untrusted text, because it contains journal messages that any local process
  can write (`hermes_client.with_context`). `desktop_notify` escapes `& < >`,
  because Plasma interprets simple HTML.
- **Missed runs:** The gateway is tied to the Plasma session. If you log in
  only after the set time, the report is caught up once as soon as the gateway
  starts (`cron.catch_up_missed`, on by default in Hermes); several missed days
  become one run.
- **Time zone:** Hermes evaluates cron expressions in the `timezone` from
  `~/.hermes/config.yaml`, otherwise in the system's time zone
  (`hermes_time.py`). The template sets none, so the system's applies; out of
  the box that is Europe/Berlin (`/etc/localtime`, `20-agent-layer.sh`).
  Earlier the file was missing, in which case UTC applies, and in VM 112 the
  report came two hours late.

## Testing

Without Hermes, anywhere with Python 3.9 or newer:

```sh
python3 tests/report-check.py
```

It replaces the commands with fixtures (rpm-ostree, skopeo, journalctl, df,
systemctl, flatpak) and checks the summary, the thresholds, the composefs
root, the comparison with the previous day, missing commands, the state and
`desktop_notify` up to the call of `hermes-os-tray --discuss`. `make lint` and
the gate (`80-validate.sh`, 7h) run it; the gate also checks
`hermes-os-morgenbericht --check` and that `ujust --list` shows both recipes.
`tests/venv-smoke.sh` loads `os_report` and `desktop_notify` through the real
plugin loader.

In the test VM (see [testumgebung.md](testumgebung.md)):

```sh
ujust hermes-morgenbericht-ein 08:30
hermes cron list                                       # job hermes-os-morgenbericht, no-agent
hermes cron run hermes-os-morgenbericht                # at the next tick instead of waiting until tomorrow
ls ~/.hermes/cron/output/*/                            # output of the run
journalctl --user -u 'hermes-os-notify-*' -n 20        # the waiting notification
```

## Pitfalls

- **Scripts only from `~/.hermes/scripts/`.** Hermes resolves symlinks and
  rejects anything that ends up outside; a link to `/usr/libexec` does not
  work. That is why the recipe creates a small file that jumps into the image
  with `exec`. If the file is gone, the job reports “Script not found”; `ujust
  hermes-morgenbericht-ein` creates it again.
- **Empty output means “silent” to Hermes.** That is why the entry point
  always prints the summary and the delivery result, so the run shows up in
  the history (`~/.hermes/cron/output`).
- **`df -P` and `--output` exclude each other.** GNU df aborts on the
  combination; the test rejects it.
- **composefs:** On bootc, `df /` shows the read-only image at 100 %.
  `/sysroot` is measured instead; otherwise every morning would say
  “/ nearly full” („/ fast voll“).
- **The notification waits in its own user unit**
  (`hermes-os-notify-*.service`), not in the gateway: a gateway restart clears
  the gateway's cgroup and would have taken the waiting `notify-send` with it.
- **Plasma decides how long the button lives.** notify-send waits until the
  notification is closed. Whether a button in the history list still works
  after the popup has been hidden is still to be checked in the VM.

## Open items

- Finish the check in test VM 112. On 2026-09-27 a one-off check ran
  there: the job without a model (2.5 s), the notification with “Discuss in
  chat” with the icon running and with it quit (then `--discuss` starts an
  instance), the comparison with the previous day, the disk space of the bootc
  disk, and `-aus` removing the job and the script. Still open: runs at the set
  time in daily use, including the time zone; a catch-up run right after
  login, when Plasma's notification service may not be ready yet; an empty
  report bubble on a freshly started icon, seen once and not reproduced.
- Sending the report to messaging platforms as well (`deliver telegram` and
  the like), if the user wants that; today it is deliberately desktop only.
