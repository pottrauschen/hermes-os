# The boundary: what asks first and what runs freely

Dangerous changes to the running system ask first; everything else runs freely.
This is a **system boundary, not a data boundary**: everything in the user's home
is free, including user units, autostart entries, `~/.ssh` and network access.

The actual barrier against system changes is that the user has no root without a
password (sudo, pkexec and run0 ask for it). The hook makes sure the agent asks
*before* it tries, and that reboot and shutdown are never run at all. It
recognizes commands, not effects.

Enforced in three places:

1. **System prompt section** in `plugins/hermes_os/__init__.py`, model-dependent.
2. **`approvals.smart_policy`** in `config.yaml.default` for Hermes' Guardian,
   model-dependent and only for commands that Hermes' own detector flags.
3. **`pre_tool_call` hook** in `plugins/hermes_os/boundary.py`, deterministic.
   Only this part is tested (`tests/boundary-check.py`).

## Hook contract according to upstream (v2026.9.24)

Source: `hermes_cli/plugins.py` (`_get_pre_tool_call_directive_details`,
`_resolve_block_from_details`), `hermes_cli/plugins_dispatch.py`
(`invoke_hook`), `tools/approval.py` (`request_tool_approval`,
`_run_approval_gate`).

| Return value | Effect |
|---|---|
| `None` | free |
| `{"action": "block", "message": …}` | veto; the message becomes the tool result. Without `message`, Hermes ignores the veto. A `block` from any plugin beats every `approve`. |
| `{"action": "approve", "message": …, "rule_key": …}` | human approval dialog (CLI prompt, gateway `/approve`, tray icon). Does not go through the Guardian; a human decides. `rule_key` sets the granularity of “always allow”. |
| `{"action": "modify", "args": …}` | changes the arguments; not used here |

There is no `deny` value; refusing uses `block`.

- **Exception in the hook:** Hermes itself turns it into a `block` (policy hook,
  fail-closed), and does the same on a timeout (`plugins.hook_callback_timeout`,
  default 30 s). The hook catches its own errors first and answers with
  `approve` and a note that the check failed. The user decides, instead of the
  command failing silently.
- **Without a human:** in cron, `-q` and unattended platforms, `approve` is
  decided by `approvals.cron_mode`, `single_query_mode` and `unattended_mode`
  (set to `deny` in hermes-os); otherwise it is blocked.
- **Switching it off:** `--yolo`, `/yolo` in the gateway or `approvals.mode: off`
  wave every `approve` through. `block` still applies.

## What Hermes catches itself

`tools/approval_detection.py`, before every terminal command, independent of the plugin.

- **Hardline, always refused, even with yolo:** `rm -rf` on `/`, system
  directories and the home, `mkfs`, `dd` to block devices, redirection to block
  devices, fork bomb, `kill -1`, `shutdown`, `reboot`, `halt`, `poweroff`,
  `init 0/6`, `telinit 0/6`, `systemctl poweroff|reboot|halt|kexec`. Only in
  command position, with the prefixes sudo, env, exec, nohup, setsid, time; the
  list does not know `pkexec reboot`, `run0 reboot`, `loginctl poweroff` or
  D-Bus calls.
- **Dangerous, asks (with `mode: smart`, the Guardian decides first):** `rm -r`,
  `chmod 777`, `chown -R root`, writing via `>`/`tee`/`cp`/`mv` to `/etc/`,
  `~/.ssh`, shell rc files and credentials, `systemctl stop|restart|disable|mask`,
  `curl | sh`, `find -delete`, `xargs rm`, `sudo -S` without a stored password.
- **File tools** (`write_file`, `patch`): writing under `/etc/`, `/boot/` or
  `/usr/lib/systemd/` asks.

## What depends on the hook alone

The `power` group is refused; all other groups ask.

| Group | Examples |
|---|---|
| `power` | `reboot`, `poweroff`, `halt`, `shutdown`, `systemctl reboot\|poweroff\|halt\|kexec\|soft-reboot\|rescue\|emergency`, `systemctl start\|isolate\|set-default reboot.target` (and the other power targets), `loginctl poweroff`, `init 0/1/6`, login1, systemd1 and KDE shutdown via `busctl`/`dbus-send`/`gdbus`/`qdbus` |
| `sleep` | `systemctl suspend\|hibernate`, `loginctl suspend` |
| `sudo` | `sudo`, `pkexec`, `doas`, `run0`, `su -c`, `machinectl shell` with a command outside the allowlist; `distrobox --root` |
| `root-shell` | `sudo -i`, `sudo -s`, `sudo bash`, `su`, `pkexec`/`run0` without a command, `machinectl shell .host`, `sudo chroot /sysroot` |
| `image` | `bootc upgrade\|switch\|rollback …`, `rpm-ostree install\|override\|kargs …`, `ostree admin …` (except `status`), `systemd-sysext merge`, `ujust update` and related recipes |
| `ujust` | every recipe except `hermes-*`, `changelogs` and pure display options (`--list`, `--show`) |
| `services` | `systemctl start\|enable\|mask …` without `--user`, `systemd-run` without `--user`, `machinectl start …`, `service`, `init 3` |
| `system-files` | redirections `>`/`>>`/`&>`/`>&` and file commands (`tee`, `cp`, `mv`, `install`, `ln`, `rm`, `chmod`, `sed -i`, `touch`, `mkdir`, `curl -o`, `wget -O`, `tar -C`, `unzip -d`, `find -delete` …) with a target in a system path (see below); `sudoedit` |
| `network` | `firewall-cmd`, `nft`, `iptables` (except display), `nmcli` with changes (connections, radio, joining Wi-Fi) |
| `users` | `useradd`, `passwd`, `chsh`, `visudo`, `authselect` … |
| `boot` | `grubby`, `dracut`, `kernel-install`, `bootupctl`, `mokutil`, `efibootmgr` with changes, `bootctl` except `status` |
| `disks` | `fdisk`, `parted`, `mkfs.*`, `wipefs`, `cryptsetup`, `mount`/`umount` with operands, `dd of=/dev/…` |
| `system-config` | `localectl\|timedatectl\|hostnamectl set-*`, `hostnamectl hostname X`, `sysctl -w`, `date -s`, `hwclock -w`, `loginctl enable-linger` |
| `flatpak-system` | `flatpak install\|remove\|update … --system` |
| `ssh`, `kernel`, `security`, `session` | `ssh-keygen`, `ssh-copy-id`; `modprobe`, `rmmod`; `setenforce`, `semanage`, `setcap`, `update-crypto-policies --set`; `loginctl terminate-*`, `kill -9 -1` |
| `firmware` | `fwupdmgr update\|install\|…` (polkit often allows this without a password in active sessions) |

`image` also covers `pkcon install|update|remove` and `just -f /usr/share/ublue-os/justfile …`
(the ujust rules apply there). `bootc upgrade --check` and `rpm-ostree upgrade
--check|--preview` stay free, even with sudo; so does `reboot --help`.

**System paths** for redirections and file commands: `/`, `/etc`, `/usr`, `/boot`, `/var`,
`/ostree`, `/sysroot`, `/root`, `/opt`, `/srv`, `/proc`, `/sys`, `/dev`, `/run`, `/lib`,
`/bin`, `/sbin`. Excluded: `/var/home` (the home), `/var/tmp`, `/run/user`,
`/run/media`, `/dev/null`, `/dev/zero`, `/dev/std*`, `/dev/tty`, `/dev/fd`, `/dev/pts`,
`/dev/shm`, `/dev/tcp`, `/dev/udp`, `/proc/self/fd`.

**Root shells write everywhere as root:** in `sudo sh -c '…'`, `su -c`, `pkexec sh -c`
and `sudo -i …`, every writing redirection asks, even into the home; only `/dev/null`,
`/dev/std*`, `/dev/fd` and `/dev/tty` stay free.

The classifier splits the command the way a shell does (quotes, escapes, line
continuation, tabs, `;`, `&&`, `||`, `|`, `&`, parentheses, heredocs,
here-strings, `$(…)`, backticks, `<(…)`) and recursively unwraps
`sh -c`/`bash -c`, `eval`, `xargs`, `find -exec`, `env`, `nice`, `nohup`,
`timeout`, `time`, `exec`, `command`, `watch`, `stdbuf`, `ionice`, `setsid`,
`flock`, `script -c`, `strace`, `ltrace`, `gdb --args`, `unshare`, `setarch`,
`prlimit`, `runuser`, terminals with `-e` (`konsole`, `xterm` …),
`systemd-run --user`, `flatpak-spawn --host`, `distrobox-host-exec`,
`host-spawn`, `toolbox run --host`, `nsenter`, `chroot`, `machinectl shell`.
Keywords (`if`, `then`, `do`, `{`, `!`, `function f`, `coproc`) are skipped, and
`$'…'` is resolved as in Bash (`\xHH`, octal, `\u`). Text that flows into a
shell or into `at`/`batch` via `echo`/`printf`, a heredoc, a here-string or
process substitution (`bash <(…)`, `source <(…)`) is checked as well. Paths are
normalized (`//etc/./x`, `/usr/../etc`). The check runs in linear time;
`tests/boundary-check.py` measures this with long inputs, because Hermes blocks a
hanging hook after 30 s but lets the worker keep running.

**Tools:** the hook checks `terminal` (`command`) and `process_manage` with
`write`/`submit` (`data`, text typed into a running process, such as a
background shell).

The approval granularity is `hermes-os:<group>:<command>`: “Always allow”
(German default: „Immer erlauben“) for `sudo python3` does not also allow `sudo rm`.

## Allowlist: free even with root privileges

Behind `sudo`, `pkexec`, `doas`, `run0` and `su -c`, pure read commands stay
free: `journalctl` (without `--vacuum`, `--rotate`, `--flush`), `dmesg` (without
`-C`, `-c`), `cat`, `less`, `more`, `head`, `tail`, `grep`, `wc`, `file`,
`stat`, `ls`, `tree`, `find` (without `-exec`, `-delete`), `lsblk`, `lspci`,
`lsusb`, `lsmod`, `lscpu`, `lsof`, `findmnt`, `df`, `du`, `blkid`, `diff`,
checksum tools, `systemctl status|show|cat|is-*|list-*`, `bootc status`,
`rpm-ostree status`, `ostree admin status`, `nmcli` without changes,
`firewall-cmd --list-*|--get-*|--query-*|--state`, `nft list`,
`iptables -L|-S`, `ip` without changes, `localectl|timedatectl|hostnamectl`
without setting anything, `loginctl list-*|show-*`, `fdisk -l`, `parted … print`,
`bootctl status`, `efibootmgr` without changes, `fwupdmgr get-*`.

Without root, everything that matches no group stays free: `systemctl --user`,
`flatpak install --user`, `flatpak run`, `podman`, `distrobox create/enter`,
`grep -r /etc/…`, `cat /etc/os-release`, `ls /usr/share`, `kwriteconfig6`,
`git`, everything in the home. `flatpak install` without `--system` also stays
free, even though Aurora then installs system-wide. That is intended (apps are
free).

## Known gaps

The hook sees the command string, not what it does.

- **Interpreters and scripts:** `python3 -c "os.system('sudo reboot')"`, a
  shell script in the home, `make`, `npm run`. With sudo in front, it asks;
  without sudo, the system change fails for lack of root.
- **Other tools:** the hook does not check `execute_code`; Hermes asks there
  itself, in the gateway and the CLI. `cronjob_manage` with `script` runs a
  script file on a schedule; the hook does not see its content. It sees
  `process_manage` only on `write`/`submit`, not what an already running process
  does otherwise. Hermes itself guards `write_file` and `patch` for `/etc`,
  `/boot` and `/usr/lib/systemd`.
- **Shell text from sources other than** `echo`/`printf`, heredocs and
  here-strings: Hermes' detector catches `base64 -d … | sh`, and `curl … | sh`
  as well; `cat file | sh` and similar it does not.
- **Indirection:** command names from variables (`$CMD`), aliases and functions
  from earlier calls, globs in paths (`/et?/x`), relative paths when the working
  directory is under `/etc` (the tool's `workdir`).
- **Other routes to polkit:** `gdbus`/`busctl` for actions other than power,
  graphical tools that ask for the password themselves.
- **Other machines:** `ssh nas sudo reboot` affects another machine and stays
  free.
- **Approvals switched off:** with yolo or `approvals.mode: off`, every
  `approve` goes through; only `power` stays refused.
- **Other wrappers:** tools not listed above (such as `parallel`,
  `tmux send-keys`, `expect`, `make`) hide the command behind them; without sudo,
  that command has no root.

## Maintenance

New cases go into `tests/boundary-check.py` (`CASES`). `make lint` checks them
without Hermes; `tests/venv-smoke.sh` and the gate (`80-validate.sh`) send the
same list through the real plugin loader of the release. Before a Hermes bump,
check the contract above against `hermes_cli/plugins.py`.
