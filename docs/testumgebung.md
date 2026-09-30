# Test environment: building and booting in the homelab

Where hermes-os boots while no machine is free for it: on the Proxmox host
`<proxmox-host>`, following the pattern of the ainux project. The image comes
ready-made from CI; the homelab only turns it into a disk, and that disk boots
in a test VM. The route via `bootc switch` on a real machine is in the README
and remains the route for devices.

## What is involved

| What | Where | Properties |
|---|---|---|
| Build VM `ainux-build` | VM 110 on `<proxmox-host>`, `<user>@<build-vm>` | Fedora Cloud 44, rootful Podman, bootc-image-builder, 4 cores, 4 GB, 80 GB disk |
| Test VM `hermes-test` | VM 112 on `<proxmox-host>`, `<user>@<test-vm>` (DHCP) | q35, OVMF without Secure Boot, 4 cores, 8 GB; RTX 3060 via passthrough (`hostpci0: 0000:0c:00,pcie=1`), `vga: none`, picture on the 3060's HDMI, keyboard and mouse through the KVM switch (`usb0: host=5-6.1.4.1`); boots `hermes-os-nvidia`; 64 GB disk |
| Staging area for the disk | `<proxmox-host>`, `/zfspool0/iso/transfer/` | on the ZFS pool, not in `/tmp` |

The build VM belongs to the ainux project and is shared (decision
2026-09-26). hermes-os only creates `~/hermes-os` there, plus the pulled image
in Podman's root storage; the disk was grown from 40 to 80 GB for this.

**110 and 112 never run at the same time.** The host has roughly 9 to 15 GB of
RAM free, depending on which other VMs are running. The sequence is therefore
serial: build, stop 110, start 112. Stopping 110 during a build aborts it; the
restart only repeats the disk build, not the pull.

## Steps

1. **Get the image onto the build VM.** On 110, into root storage, because the
   builder only sees that one:

   ```sh
   sudo podman pull ghcr.io/pottrauschen/hermes-os:latest
   ```

2. **Build the disk.** `~/hermes-os/build-qcow2.sh` on 110 calls
   bootc-image-builder exactly like the Makefile target `qcow2`, just without
   the repo. The configuration `~/hermes-os/config.toml` corresponds to a
   `disk.local.toml`: user `admin` in `wheel`, password and the workstation's
   SSH key. Before building, the script prints the image's identifier, digest
   and version; read that line and compare it with `bootc status` in the
   booted VM. Result: `~/hermes-os/output/qcow2/disk.qcow2`.

3. **Import the disk.** On `<proxmox-host>` as root: `/root/hermes-import.sh`
   fetches the file from 110 via SSH onto the ZFS pool, imports it with
   `qm importdisk` into `vmdata`, attaches it as `scsi0` with
   `discard=on,iothread=1`, sets the boot order and deletes the intermediate
   file. For this, the RSA key of `root@<proxmox-host>` is listed in the
   `authorized_keys` of `admin` on 110; the build VM itself holds no private
   key and cannot reach any other machine.

4. **Boot.** `qm stop 110`, `qm start 112`. The address comes from the guest
   agent that Aurora ships:

   ```sh
   qm guest cmd 112 network-get-interfaces
   ```

5. **Check.** `tests/boot-check.sh` covers the SSH parts of the boot checklist
   (section below):

   ```sh
   ssh <user>@<address> 'bash -s' < tests/boot-check.sh <id-from-step-2>
   ```

   The first-login terminal, the approval dialog, language and the AT-SPI tree
   need the graphical session: Proxmox console of VM 112, log in as `admin`.

The disk build is only needed for the very first boot. The booted VM tracks
`ghcr.io/pottrauschen/hermes-os:latest` as its origin, and the package is
public; every later version arrives the same way as on a real device:

```sh
sudo bootc upgrade          # fetches latest, stages the deployment
systemctl reboot            # activates it
```

On 2026-09-26 this took 38 seconds for a changed layer (450 MB), plus a
reboot in under a minute. If you build a new disk anyway: `qm set --scsi0`
turns the old one into `unused0`, and it keeps taking up space on `vmdata`;
after the swap, run `qm set 112 --delete unused0`.

## GPU passthrough: RTX 3060 on VM 112

Since 2026-09-26 the host's RTX 3060 (`0c:00`, GA106, 12 GB) has been attached
to the test VM, so that Whisper, speech output and local models can run on the
GPU. The host was already prepared (`amd_iommu=on iommu=pt`, both NVIDIA cards
on `vfio-pci`, separate IOMMU groups); the steps were:

1. In the running VM, switch to the NVIDIA variant, staged only:
   `sudo bootc switch ghcr.io/pottrauschen/hermes-os-nvidia:latest`
   (36 new layers, 2.4 GB, about five minutes).
2. Shut the VM down (`sudo systemctl poweroff` inside the VM; `qm shutdown`
   can hang on Plasma's prompt), then on the host
   `qm set 112 -hostpci0 0000:0c:00,pcie=1` and `qm start 112`.
   The audio function `0c:00.1` comes along through the multifunction notation.
3. Check: `nvidia-smi` reports the card, `lsmod` shows `nvidia`,
   `nvidia_drm`, `nvidia_modeset`, `nvidia_uvm`; driver 615.71.09 with the
   license “Dual MIT/GPL”, so the open kernel modules.
   `tests/boot-check.sh 44.20260922.1.20260926` reported no hard errors.

At first the VM ran without `x-vga` and with `vga: virtio`: the Proxmox
console showed the desktop, and the 3060 was a pure compute card. Since
2026-09-27 VM 112 has been on `vga: none`: Plasma runs on the 3060, the
picture goes out over its HDMI to the monitor on the KVM switch, keyboard and
mouse come in over the passed-through USB port. The Proxmox console therefore
stays black, and `qm monitor … screendump` returns nothing; the session is
operated from here as described in the section “Operating VM 112 from here”.

Constraints: the 3060 is also in the configs of VM 105 and 107 (render VM);
while it is attached to 112, neither of them starts. With passthrough the
guest RAM (8 GB) is pinned. The Quadro P620 (`04:00`, Pascal) is no use:
`aurora-dx-nvidia-open` supports Turing and later only, and NVIDIA ends Pascal
support with the 580 series.

## Operating VM 112 from here

The VM no longer has a Proxmox console (`vga: none`). Everything the session
needs still works from the Windows PC; the helpers for it are in
`tests/vm-hilfen.sh`.

| What | How |
|---|---|
| Log in at the login screen | on the host `<proxmox-host>` as root: `qm sendkey 112 shift`, then the password key by key, then `ret`. On a German layout, `-` sits on the US key `slash`: `for k in h e r m e s slash o s; do qm sendkey 112 $k; done; qm sendkey 112 ret` |
| Commands in the session | `ssh <user>@<test-vm>`, then `. ~/hosenv.sh` (a copy of `tests/vm-hilfen.sh`, see the file's header). Sets `WAYLAND_DISPLAY`, `DBUS_SESSION_BUS_ADDRESS` and the rest of the Plasma session's environment |
| Screenshot | `shot` writes `~/hos/s.png` (`shotp` with the pointer), then `scp <user>@<test-vm>:hos/s.png .` to the PC |
| Clicking and typing | `VM_PASS=… prep` once per session (ydotool daemon, flat pointer acceleration), then `click X Y` and `paste "Text"`. If a user without sudo is logged in: `prep` as the admin user, then `flach` as that user |
| Recording the screen | `rec_start` presses Spectacle's shortcut “Record Screen” (German default: „Bildschirm aufnehmen“) and makes the click it asks for; `rec_stop` prints the file's path; then `scp` to the PC |
| Asking Hermes without a keyboard | `frage "…"` sends the question into the Kontor (the chat window), `frage_still "…"` answers as a notification (the tray icon's runner over D-Bus) |
| Showing the tray icon | `/usr/libexec/hermes-os-tray --show` (hands over to the running instance) |

Anyone sitting at the VM sees what these helpers do: windows open, the pointer
moves. Say so beforehand. For pictures of interfaces that should not disturb
anyone, there are the offscreen tests (`docs/entwicklung.md`, “Checking
interfaces without a screen”).

## Pitfalls

- **`/tmp` on the host is a tmpfs in RAM.** The ainux docs put the disk there,
  at 3.5 GB. The hermes-os qcow2 is several times that size and would push out
  the RAM the test VM needs. Hence the ZFS pool.
- **Aurora declares `btrfs` as the root filesystem** in
  `/usr/lib/bootc/install/20-aurora.toml`. The Makefile sets `--rootfs`
  anyway, because the bare Universal Blue base image aborts without it, and
  this keeps the choice visible.
- **New disk, new host keys.** After every swap, `ssh` reports
  “REMOTE HOST IDENTIFICATION HAS CHANGED”. The right fix is
  `ssh-keygen -R <address>`, not turning the check off.
- **`sudo` in the test VM asks for the password.** Checks that need root
  therefore run via `ssh -t` with input, or at the console.
- **Secure Boot is off in VM 112**, because the image is not signed yet. Once
  `SIGNING_SECRET` and `cosign.pub` exist, this needs testing.
- **SSH is off in the image.** Aurora does not start sshd, and the disk
  inherits that. Through the guest agent only `systemctl enable sshd` works,
  meaning the symlink, not the start: the agent runs in an SELinux context
  that is not allowed to drive systemctl. A reboot activates the service; at
  the console, `sudo systemctl enable --now sshd` is enough.
- **Aurora's first-run setup starts even though a user exists.**
  `plasma-setup.service` runs as long as `/etc/plasma-setup-done` is missing;
  the builder creates the user, not the marker. Either go through the wizard
  at the console, which wants to create another user, or run
  `sudo touch /etc/plasma-setup-done` as the user and reboot. Then the login
  screen of plasmalogin appears, Aurora's login manager in place of SDDM.
- **Kernel command line with `console=ttyS0`.** The builder adds it; without a
  serial port, agetty logs an error every ten seconds. VM 112 therefore has
  `serial0: socket`, and `qm terminal 112` gives a console.
- **Journal noise from Aurora.** During early boot, udev does not resolve
  groups such as disk, kvm, tss and plugdev, and there are two SELinux notices
  on top (lsblk against the userdb, chcon with mac_admin). None of this comes
  from the hermes-os layer; `tests/boot-check.sh` filters out the known noise.
- **Screenshots without logging in** only worked with `vga: virtio`:
  `echo "screendump /root/112.ppm" | qm monitor 112` on the host, and
  `/root/ppm2png.py` there converts the PPM to PNG. With `vga: none` the
  picture stays black; then use Spectacle in the session (below).
- **A screenshot from the session shows an old picture** when the display is
  off through DPMS: `spectacle --background` then returns the frozen frame,
  old clock included. Run `kscreen-doctor --dpms on` through
  `systemd-run --user` first, and the screenshot is right; `wake` in
  `tests/vm-hilfen.sh` does exactly that.
- **Without a monitor on the 3060 there is no session.** After startup, all
  connectors report `disconnected` as long as the KVM switch has never been
  set to the VM: KWin has no output, plasmashell crashes in a loop, screenshots
  and recordings fail. Switching to the VM once is enough; after that HDMI
  stays connected, even when the switch goes back.
  Check: `grep . /sys/class/drm/card0-*/status`.
- **Spectacle only starts recording after a click.** “Record Screen” (German
  default: „Bildschirm aufnehmen“) shows a crosshair and waits to be told which
  screen is meant; without a click it quits silently, with nothing in the log.
  `rec_start` clicks; a `ydotool click 0xC0` in one go does not register
  there, but press and release sent separately do. The file lands in the
  localized subfolder, in a German session `~/Videos/Bildschirmaufnahmen`. A
  Spectacle screenshot during the recording goes to the same instance and ends
  it; `shot` therefore calls `spectacle --new-instance`, as Hermes' own visual
  check does, and the recording keeps running. Whether a recording is running
  shows in the panel entry “Spectacle” (`_rec_laeuft`); the shortcut itself
  only toggles.
- **Growing the disk only works with sudo in the VM.** Because of SELinux, the
  guest agent may neither open `/dev/sda` nor call `systemd-run`. Steps: on the
  host `qm resize 112 scsi0 +32G`, in the VM `sgdisk -e /dev/sda`,
  `echo ",+" | sfdisk -N 4 --no-reread --force /dev/sda`, `partx -u -n 4
  /dev/sda`, `btrfs filesystem resize max /var`. `parted` refuses the mounted
  partition, and `/sysroot` is mounted read-only.
- **ydotool types a US layout.** On a German keyboard, `ydotool type` swaps
  y and z and gets special characters wrong; text therefore goes through the
  clipboard (`paste`). Start `wl-copy` with no output streams left open,
  otherwise it keeps the SSH session open.
- **Without a graphical login, the gateway dies with the SSH session.** After
  a reboot the VM waits at the login screen, with no autologin; the user units
  only start with the Plasma session. `systemctl --user start
  hermes-gateway` from SSH only runs as long as that session is open, because
  without linger the user manager ends with the last session. So start and
  test within one SSH session, or log in at the console.
- **Keyboard and language do not come from the builder.** bootc-image-builder
  has no locale customization; without defaults in the image, the disk boots
  with a US keyboard and English. Plasma reads the keyboard from `kxkbrc`,
  otherwise from `localectl`. KWin listens through KConfigWatcher: a change
  takes effect immediately when `kwriteconfig6 --notify` writes it, otherwise
  only at the next login. The D-Bus signal `reloadConfig` does nothing in
  KWin 6.7.

## Measurements from the first run (2026-09-26)

| Step | Value |
|---|---|
| Pulling the image on 110 | 6 GB compressed, 16.3 GB in storage, about 20 minutes |
| Disk build on 110 | 32 minutes with 4 cores and 4 GB |
| qcow2 | 7.35 GB file, 32 GB virtual disk |
| Transfer from 110 to the host | about 300 MB/s, under a minute |
| Import into vmdata | about 2 minutes |
| Boot until the guest agent answers | about 20 seconds, SSH right after |

The version that booted was `44.20260922.1.20260925`, with kernel 7.1.10; the
check script reported no hard errors. Later versions came via `bootc upgrade`
(450 MB, 38 s) and `bootc switch` to the NVIDIA variant (2.4 GB, about five
minutes).

## Boot checklist, as of 2026-09-26

| Item | Result |
|---|---|
| First login | Passed. Config from the template, plugin and skill linked, plugin enabled. Setup through the assistant from `~/hos` (test build, in the image from the next CI run on), OpenRouter with a key. After the upgrade to `44.20260922.1.20260926`, the script created `API_SERVER_KEY` in `.env` at login and enabled the gateway. |
| Tray icon (`docs/systemagent.md`) | Automated part passed: the icon starts through autostart, creates the conversation `hermes-os-tray` on the API server, no QML errors in the journal, `/health` answers, `--show` from a second instance exits at once (hand-over). Open, only checkable at the screen: icon color, Meta+H, answer in the window, approval box and notification. |
| NVIDIA variant | Passed on 2026-09-26 with the RTX 3060 via passthrough: `hermes-os-nvidia` boots, open kernel modules 615.71.09 loaded, `nvidia-smi` shows 12 GB. Whether Whisper and Piper use the GPU has not been checked yet. |
| `hermes` in the terminal, plugin loaded | Passed. `hermes chat -q` with a question about deployments returned the image reference and version from `os_status`. |
| `app_launch` | Passed. Started from the session (`systemd-run --user`), Konsole appeared. Not testable over SSH without the session environment. |
| Approval dialog | Open, only checkable interactively: `sudo bootc upgrade --check` in the chat must ask, `flatpak install` must not. |
| Gateway | Passed. After saving, the assistant calls the first-login script, which enables the unit; `enabled`/`active`, OpenRouter key in the credential pool. Since 2026-09-26 with the API server on `127.0.0.1:8642`, and the key from `.env` is accepted. Note in the journal: the unit has `TimeoutStopSec=30s`, while Hermes expects values that fit `drain_timeout` (“Stale systemd unit detected”); not aligned yet. |
| Voice (`/voice on`) | Open, needs a microphone in the VM. |
| Keyboard and system language | Failed on 2026-09-26 with the first disk: y came out as z, Plasma in English. Cause: the disk from the builder carries neither locale nor keyboard, only the Anaconda installer asks for them; the model used for testing then invented keys in `kdeglobals` and `kwinrc`. Set by hand in VM 112, since then defaults in the image and the recipe in the skill. Passed on the evening of 2026-09-26 after `bootc upgrade` to digest `2eb6e1a5…`: defaults under `/etc` and `/etc/xdg` present, `localectl` reports de/de/de, the agent confirms it via `os_locale`. |
| Library (`docs/bibliothek.md`) | Passed on 2026-09-26: `library_list` through the gateway in the booted image names the entry docs.kde.org; before that, the full run from `~/hos` with `library_fetch` (Dolphin handbook with source in 30 s). The page in the window was checked offscreen, not yet on screen. |
| `ujust --list` | Passed, eight recipes. |
| AT-SPI (Phase 3) | `busctl --user tree org.a11y.atspi.Registry` returns no tree; turn on accessibility in the KDE settings once Phase 3 begins. |

`hermes doctor` is green apart from optional packages, OpenRouter reachable.
Irrelevant for hermes-os: “~/.local/bin/hermes not found” (our launcher lives
under `/usr/bin`), ripgrep and Node missing (optional).
