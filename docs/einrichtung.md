# Setup: assistant at first login, dashboard afterwards

As of 2026-09-26. How a user connects Hermes on hermes-os to a language model
without needing a terminal, and what the image ships for it.

## Two parts

1. **Assistant for the first login.** A Kirigami window that the first login
   opens: choose a provider, enter and check the key, choose a model, done.
   Built, in the image.
2. **Dashboard for everything after that.** With `hermes dashboard`, Hermes
   ships a web interface for models, keys, provider login, sessions, cron,
   plugins and skills. The frontend is built in the Node stage of the
   Dockerfile, the window uses QtWebEngine, and it opens from the menu, the tray
   icon, the assistant and `ujust hermes-dashboard`. Separate documentation:
   [dashboard.md](dashboard.md).

## Part 1: the assistant

### Files

| What | Where |
|---|---|
| Launcher, Python with PySide6 | `files/system/usr/libexec/hermes-os-setup` |
| Interface, QML with Kirigami | `files/system/usr/share/hermes-os/setup/Main.qml` |
| Bridge into the Hermes venv | `files/system/usr/share/hermes-os/setup/hermes_bridge.py` |
| Menu entry “Set up Hermes” (German default: „Hermes einrichten“) | `files/system/usr/share/applications/hermes-os-setup.desktop` |
| Render test without a display | `tests/setup-gui-check.py` |

PySide6, Kirigami and QtWebEngine are part of the Aurora DX image (as packages
of the Kinoite base, not chosen by Aurora itself; `15-dashboard.sh` makes sure
of them with a dnf call that is normally a no-op). The assistant runs with
Fedora's Python, not with the Hermes venv, and calls the bridge as a subprocess
in the venv for everything Hermes-specific. The bridge speaks JSON and gets the
key only through the environment variable `HERMES_OS_SETUP_KEY`, never as an
argument.

### What the bridge does

- `catalog`: Hermes' provider catalog (`hermes_cli.provider_catalog`),
  filtered to providers with an API key, plus Nous Portal. Local servers,
  cloud SDK auth and aggregate routes without their own key are left out. The
  list is Hermes' list, not ours.
- `models <slug>`: base URL as in the wizard, model list via
  `probe_api_models`, key check. OpenRouter answers `/models` even without a
  key, so the check uses `/key` there; other providers require auth for
  `/models`, so the list is what counts. Result: `ok`, `rejected` or `unknown`.
- `save <slug> <model>`: `save_env_value` for the key in `.env`,
  `_persist_model` for provider, model and base URL in `config.yaml`, exactly
  the helpers that `hermes setup` uses. OpenRouter gets
  `api_mode: chat_completions`; all others leave `api_mode` out.
- `check`: dry run for the validation gate, without network access and without
  writing.

These helpers are internal Hermes functions with no stability promise. The pin
on `HERMES_REF` protects against that; on a Hermes bump,
`hermes-os-setup --check` and the render test are mandatory.

### Steps in the window

The assistant is not translated yet and shows its labels in German in every
session; they are quoted below with a translation.

1. **Welcome**: what Hermes is, the Hermes version, a note if a provider is
   already set up, and a way out: „Lieber im Terminal einrichten“ (set up in
   the terminal instead).
2. **Provider**: list from the catalog, OpenRouter first.
3. **Key and model**: password field, link to the provider's key page (copy or
   open), „Schlüssel prüfen und Modelle laden“ (check key and load models),
   model choice with the default from Hermes' catalog. Saving works only with a
   key that was checked, or at least not rejected.
4. **Done**: writes through the bridge, then runs the first-login script again,
   which switches on the gateway, and offers „Dashboard öffnen“ (open
   dashboard; as soon as `/usr/libexec/hermes-os-dashboard` is executable) and
   the chat in the terminal.

### Subscription instead of a key

Hermes knows four providers that use a login instead of a key: Nous Portal,
ChatGPT/Codex, xAI Grok (SuperGrok, Premium+) and MiniMax. The assistant marks
them in the list as „Anmeldung statt Schlüssel“ (login instead of key) and, on
the login page, starts Hermes' own flow in the terminal: `hermes portal` for
Nous, which then sets model and provider itself, and `hermes model` for the
others, where login and model choice happen in one go. The address and code
from the terminal can be opened on a phone, because the image has no browser
yet. Nous makes Hermes; this is the intended route. For ChatGPT, xAI and
MiniMax, their own terms apply; those were not checked.

Anthropic's Consumer Terms allow automated access only with an API key. For
Anthropic, the bridge therefore accepts only API keys and rejects a token with
the prefix `sk-ant-oat`; the interface says so on the Anthropic page. Decided
on 2026-09-26.

For the same reason, `config.yaml.default` sets `auth.adopt_external_logins:
false`, so Hermes does not take over a login from another tool in the user's
home on its own.

The pages are permanently instantiated items, not `Component`s. When a
`Component` is pushed, Kirigami warns with “Created graphical object was not
placed in the graphics scene”; with items the warning stays away, and input
survives going back a page.

### First login and recipes

`hermes-os-first-login` opens the assistant at the very first login, provided
`hermes-os-setup --check` passes; otherwise, as before, it opens a terminal with
`hermes setup`. `ujust hermes-setup` starts the assistant,
`ujust hermes-setup-terminal` the full wizard with TTS, terminal backend,
gateway and tools. Once a provider is set up, the script also writes the key
for the gateway's local API server to `.env`; the tray icon talks to Hermes
through that server ([docs/systemagent.md](systemagent.md)).

### Testing

Without a display, without network access, with a stub instead of the bridge:

```sh
tests/setup-gui-check.py --qml-dir files/system/usr/share/hermes-os/setup --out /tmp/shots
```

Renders every page offscreen, saves PNGs and treats every QML warning as an
error. The validation gate (`80-validate.sh`, section 7c) runs the same test in
the image build; the script comes in through the build context (`/ctx/tests`),
not into the image. Runs wherever PySide6 and Kirigami are installed, for
example on an Aurora desktop or in the test VM.

In the test VM, the assistant can be started from a directory instead of
`/usr` and pushed into the running session:

```sh
systemd-run --user --unit hos-test --collect \
  -E HERMES_OS_SETUP_DIR=/tmp/hos/share/hermes-os/setup -E HERMES_HOME=/tmp/hos/home \
  /usr/bin/python3 /tmp/hos/libexec/hermes-os-setup
```

Point `HERMES_HOME` at a throwaway directory, otherwise the test writes to the
real configuration.

### Pitfalls

- Never put keys in arguments: `ps` shows them. Hence the environment variable.
- OpenRouter serves `/models` without auth; checking the key that way checks
  nothing. `/key` answers with 401 for a wrong key.
- `hermes auth add` stores keys in `auth.json` as a credential pool, not in
  `.env`, and sets neither provider nor model in `config.yaml`. That is not the
  wizard's route; hence the bridge.
- Without an installed `.desktop` file, Qt reports “Could not register app ID”.
  This happens only in the test from `/tmp`, not in the image.
- The assistant needs a graphical session. Started over SSH, it lacks
  `WAYLAND_DISPLAY`; `systemd-run --user` takes the session's environment.

## Part 2: dashboard

Built; described in [dashboard.md](dashboard.md): Node stage `webbuild` in the
Dockerfile and `15-dashboard.sh` for the frontend, the window
`/usr/libexec/hermes-os-dashboard` with `dashboard/dashboard_server.py` for
starting and stopping the server, the menu entry “Hermes Dashboard” (German
default: „Hermes-Dashboard“), the menu item “Open dashboard” (German default:
„Dashboard öffnen“) in the tray icon, a button on the assistant's done page,
`ujust hermes-dashboard`. From the second login on, the first-login script
still starts only the gateway; the dashboard runs only once someone opens the
window, and ends with it.
