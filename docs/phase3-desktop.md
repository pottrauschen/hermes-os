# Phase 3: Desktop control

As of 2026-09-25. Assessment of [kortix-ai/agent-computer-use](https://github.com/kortix-ai/agent-computer-use)
(`agent-cu`, MIT, Rust, version 0.1.1) as the basis for the third door in the blueprint:
reading and operating widgets semantically via AT-SPI instead of clicking pixels.

## What agent-cu is

A single binary with a CLI that operates any desktop app through the accessibility tree.
Core loop: `snapshot` returns the interactive elements with references (`@e5`),
`click`/`type`/`key` act, and another `snapshot` verifies the result. All output is JSON.
On top of that: `find` with selectors, `wait-for`, `ensure-text`, `get-value`, `batch`,
YAML workflows for replay, and a `SKILL.md` that teaches an agent exactly this loop.

Structure: `agent-computer-use-core` (nodes, roles, selectors, actions), one crate each for
Linux, macOS and Windows, plus Chrome DevTools for Electron and browsers.

## Why it fits hermes-os

- It is the evidence idea at desktop level: nothing counts as done until a new
  snapshot shows it. No vision tokens, deterministic.
- The Linux backend reads via AT-SPI2 on D-Bus (`zbus`). AT-SPI is independent of the
  compositor, so reading works under Wayland just as it does under X11.
- A static binary can be baked into the image. The `SKILL.md` can be adopted almost
  word for word as a Hermes skill.

## Where it falls short for hermes-os

The Linux crate splits into two halves, and only one of them works under Wayland:

| Function | Implementation in 0.1.1 | Under Plasma Wayland |
|---|---|---|
| Read the tree, find elements, text, values, list windows | AT-SPI2 via D-Bus | works |
| Click, type, keys, activate and move windows, screenshot | `xdotool` (X11) | XWayland windows only, not native Qt/GTK apps |
| Focused element | not implemented | missing |
| Permission check | only a connection test to the registry | does not switch on the a11y bus |

Clicks are translated into coordinates via `Component.GetExtents` and then executed with
`xdotool`. The AT-SPI interfaces `Action` (DoAction: click, press) and
`EditableText` (SetTextContents) are not used, although they need no pointer
and work everywhere.

Open, and only testable on the booted system: Qt apps under KDE expose their
tree only when accessibility is active (`org.a11y.Status`, or
`QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1`). agent-cu does not set this itself.

## Plan

1. **Binary into the image.** A separate CI job builds `agent-cu` from the pinned tag with Cargo
   and stores it as an artifact; `files/scripts/30-desktop.sh` copies it to
   `/usr/bin/agent-cu`. No `xdotool` in the image; that would be X11.
2. **Hermes skill** `hermes-os-desktop` from the `SKILL.md`, adapted: instead of its original
   approval rules, the hermes-os boundary applies (operating apps is free, the system
   stays behind the approval gate). Risk level: `agent-cu` writes into apps, not
   into the system, so it is free.
3. **Contribute Wayland input.** A second input layer in the Linux crate:
   first AT-SPI `Action` and `EditableText` (covers buttons, menus and text fields without
   a pointer), then `libei` via the RemoteDesktop portal for real pointer and keyboard
   input (Plasma 6 supports it, and the permission can be stored permanently).
   Activate and move windows via KWin scripting over D-Bus instead of
   `xdotool`. Scale: a few hundred lines of Rust. Offer it upstream, otherwise fork.
4. **Test on the image:** a11y bus status under KDE, read Thunderbird and Konsole via
   `agent-cu snapshot`, then a click via `Action`.

## Risks

- Young project: version 0.1.1, two npm releases, last commit in May 2026, one
  main author. The CLI interface may change, so pin the tag.
- Until step 3 is done, the agent can read under Wayland but not act.
  For "open Thunderbird", `app_launch` from phase 2 is still enough.
