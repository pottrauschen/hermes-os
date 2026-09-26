#!/usr/bin/python3
# =============================================================================
# hermes-os -- Angriffsbatterie für die Grenze (plugins/hermes_os/boundary.py)
# =============================================================================
# Befehle, die fragen oder verweigert werden MÜSSEN, und Befehle, die frei
# bleiben MÜSSEN, jeweils mit erwarteter Gruppe (None = frei). Die Liste CASES
# ist die einzige Fallliste: tests/venv-smoke.sh und das Validierungs-Gate
# (80-validate.sh) laden sie über diesen Pfad und schicken dieselben Fälle
# durch Hermes' echten Plugin-Loader.
#
# Ohne Hermes, ohne Netz, mit jedem Python 3.9+:
#   tests/boundary-check.py [--plugin-dir DIR]
# Exit 0 = alles sauber. `make lint` führt ihn aus.
# =============================================================================
import argparse
import importlib.util
import logging
import sys
from pathlib import Path

# (Befehl, erwartete Gruppe oder None). Gruppe "power" wird verweigert
# (block), jede andere Gruppe fragt (approve).
CASES = [
    # --- Neustart und Herunterfahren: verweigert --------------------------------
    ("sudo reboot", "power"),
    ("systemctl reboot", "power"),
    ("systemctl poweroff -i", "power"),
    ("shutdown -h now", "power"),
    ("loginctl poweroff", "power"),
    ("pkexec /usr/sbin/reboot", "power"),
    ("run0 systemctl kexec", "power"),
    ("bash -c 'sleep 5 && poweroff'", "power"),
    ("echo \"Neustart läuft\" && sudo reboot", "power"),
    ("x=$(sudo reboot)", "power"),
    ("echo sudo reboot | sh", "power"),
    ("bash <<EOF\nsudo reboot\nEOF", "power"),
    ("\\sudo reb\\oot", "power"),
    ("\"sudo\" 're'boot", "power"),
    ("busctl call org.freedesktop.login1 /org/freedesktop/login1 org.freedesktop.login1.Manager Reboot b false", "power"),
    ("qdbus org.kde.Shutdown /Shutdown logoutAndReboot", "power"),
    ("systemctl suspend", "sleep"),
    # --- sudo und Verwandte mit beliebigem Rest ---------------------------------
    ("sudo python3 skript.py", "sudo"),
    ("sudo perl -e 'print 1'", "sudo"),
    ("sudo node server.js", "sudo"),
    ("LANG=C sudo -E ./install.sh", "sudo"),
    ("sudo -u root env PATH=/usr/bin python3 -c 'import os'", "sudo"),
    ("/usr/bin/sudo /usr/bin/python3 -m pip install x", "sudo"),
    ("doas vim /etc/fstab", "sudo"),
    ("sudo journalctl --vacuum-time=1d", "sudo"),
    ("find ~/Downloads -name '*.rpm' -exec sudo rpm -i {} +", "sudo"),
    ("distrobox create --root --name kiste", "sudo"),
    ("machinectl shell root@.host /usr/bin/python3 x.py", "sudo"),
    # --- Root-Shells -------------------------------------------------------------
    ("sudo -i", "root-shell"),
    ("sudo su -", "root-shell"),
    ("echo 'reboot' | sudo bash", "root-shell"),
    ("pkexec", "root-shell"),
    ("machinectl shell .host", "root-shell"),
    ("sudo chroot /sysroot", "root-shell"),
    ("echo \"$(sudo -i)\"", "root-shell"),
    # --- Schreiben unter /etc, /usr, /boot, /var/lib ------------------------------
    ("echo x > /etc/foo", "system-files"),
    ("cat >> /etc/hosts <<'EOF'\n127.0.0.1 büro\nEOF", "system-files"),
    ("printf '%s\\n' \"a\" >/usr/local/bin/tool", "system-files"),
    ("echo x 1>> \"/boot/loader/entries/ö.conf\"", "system-files"),
    ("cp ~/my.conf //etc/./sddm.conf", "system-files"),
    ("sed -i 's/ä/ae/' /etc/locale.conf", "system-files"),
    ("ls *.conf | xargs -I{} sudo cp {} /etc/", "system-files"),
    ("sudo tee /etc/sysctl.d/99-x.conf < /dev/null", "system-files"),
    ("echo x | tee -a /var/lib/foo", "system-files"),
    ("curl -fsSL https://example.org/y -o /usr/local/bin/y", "system-files"),
    ("ln -sf ~/x.service /usr/lib/systemd/system/x.service", "system-files"),
    # --- Entschachteln: Hüllen um Systembefehle -----------------------------------
    ("sh -c \"bash -c \\\"sudo systemctl enable sshd\\\"\"", "services"),
    ("nsenter -t 1 -m -- systemctl start sshd", "services"),
    ("flatpak-spawn --host rpm-ostree install htop", "image"),
    ("distrobox-host-exec sudo bootc upgrade", "image"),
    ("toolbox run --host bootc switch ghcr.io/x/y:latest", "image"),
    ("systemd-run --scope systemctl status", "services"),
    ("systemd-run --user --scope sudo rpm-ostree kargs --append=quiet", "image"),
    ("timeout 30 nice -n 5 nohup sudo bootc upgrade", "image"),
    ("env -i FOO=bar\tsudo\tsystemctl\trestart\tNetworkManager", "services"),
    ("if true; then sudo useradd bob; fi", "users"),
    ("eval \"sudo rpm-ostree install vim\"", "image"),
    ("watch -n 5 'sudo systemctl restart foo'", "services"),
    ("git status\nsudo bootc switch ghcr.io/foo/bar:latest", "image"),
    ("(cd /tmp; sudo mkfs.ext4 /dev/sdb1)", "disks"),
    ("sudo -s bootc rollback", "image"),
    ("sudo -iu root", "root-shell"),
    ("find / -name '*.bak' -delete", "system-files"),
    ("init 3", "services"),
    # --- Gruppen aus der bisherigen Liste ----------------------------------------
    ("sudo bootc switch ghcr.io/x/y:latest", "image"),
    ("rpm-ostree install foo", "image"),
    ("rpm-ostree kargs --append=nomodeset", "image"),
    ("ujust update", "image"),
    ("ujust toggle-updates", "image"),
    ("ujust configure-grub", "ujust"),
    ("ostree admin pin 0", "image"),
    ("sudo systemctl enable --now sshd", "services"),
    ("bash -c 'sudo useradd bob'", "users"),
    ("sudo tee /etc/foo.conf", "system-files"),
    ("flatpak install --system flathub org.x.Y", "flatpak-system"),
    ("sudo localectl set-x11-keymap de", "system-config"),
    ("hostnamectl hostname werkstatt", "system-config"),
    ("firewall-cmd --add-port=22/tcp --permanent", "network"),
    ("nmcli connection delete \"WLAN Büro\"", "network"),
    ("ssh-keygen -t ed25519", "ssh"),
    ("sudo dd if=disk.img of=/dev/sda bs=4M", "disks"),
    ("loginctl terminate-session 2", "session"),

    # === frei ====================================================================
    ("systemctl --user restart hermes-gateway", None),
    ("systemctl --user enable --now syncthing.service", None),
    ("systemctl status sshd", None),
    ("journalctl --user -u hermes-gateway -n 50", None),
    ("flatpak install --user flathub org.gimp.GIMP", None),
    ("flatpak install flathub org.mozilla.Thunderbird", None),
    ("flatpak run org.mozilla.firefox", None),
    ("podman run --rm -it fedora:44 bash", None),
    ("podman build -t probe .", None),
    ("distrobox create --name dev --image fedora:44", None),
    ("distrobox enter dev -- sudo dnf install -y gcc", None),
    ("grep -r \"Listen\" /etc/ssh/", None),
    ("cat /etc/os-release", None),
    ("cat /etc/passwd | head", None),
    ("ls -la /usr/share/applications", None),
    ("ls /etc | grep -c conf", None),
    ("kwriteconfig6 --notify --file kxkbrc --group Layout --key LayoutList de", None),
    ("git status && ls -la", None),
    ("git status && git log --oneline -5", None),
    ("echo \"Grüße aus Köln\" > ~/notiz.txt", None),
    ("mkdir -p ~/.config/autostart && cp /usr/share/applications/org.kde.konsole.desktop ~/.config/autostart/", None),
    ("cp /etc/os-release ~/os-release.txt", None),
    ("rsync -a /etc/xdg/ ~/backup/xdg/", None),
    ("ln -s /usr/share/doc ~/doc", None),
    ("sed -i 's/alt/neu/' ~/notizen.md", None),
    ("tar -xf ~/a.tar -C ~/ziel", None),
    ("curl -fsSL https://example.org -o ~/Downloads/x.html", None),
    ("wget -P ~/Downloads https://example.org/y.iso", None),
    ("echo x 2>/dev/null > ~/out.txt", None),
    ("printf 'b\\na\\n' | sort -o ~/s.txt", None),
    ("cat <<'EOF' > ~/.config/probe.conf\n[Allgemein]\nsudo reboot\nEOF", None),
    ("echo \"reboot\" && echo 'sudo rm -rf /'", None),
    ("grep -n 'shutdown' ~/log.txt", None),
    ("python3 -c 'print(\"sudo reboot\")'", None),
    ("FOO=bar\tpython3 ~/skript.py", None),
    ("find ~/Projekte -name '*.py' -exec grep -l TODO {} +", None),
    ("ls ~ | xargs -n1 echo", None),
    ("systemd-run --user --scope firefox", None),
    ("nice -n 10 ffmpeg -i a.mkv b.mp4", None),
    ("loginctl lock-session", None),
    ("nmcli connection show", None),
    ("firewall-cmd --list-all", None),
    ("hostnamectl", None),
    ("localectl status", None),
    ("mount | grep btrfs", None),
    ("rpm-ostree status", None),
    ("ujust hermes-doctor", None),
    ("ujust --list", None),
    ("sudo -l", None),
    ("sudo journalctl -b -p err", None),
    ("sudo dmesg | tail -50", None),
    ("sudo cat /var/log/boot.log | grep -i fehler", None),
    ("sudo systemctl status sshd", None),
    ("sudo systemctl list-units --failed", None),
    ("sudo bootc status", None),
    ("sudo rpm-ostree status", None),
    ("sudo lsblk -f", None),
    ("sudo ls -la /root", None),
    ("sudo stat /etc/shadow", None),
    ("sudo lspci -k && sudo lsusb", None),
    ("sudo nmcli device status", None),
    ("sudo grep -r 'PermitRootLogin' /etc/ssh/", None),
    ("sudo find /var/log -name '*.log'", None),
    ("sudo head -n 20 /var/log/dnf.log", None),
    ("ssh nas uptime", None),
]


def load_boundary(plugin_dir: Path):
    spec = importlib.util.spec_from_file_location("hermes_os_boundary", plugin_dir / "boundary.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def expected_action(group, block_groups=frozenset({"power"})):
    """Hook-Aktion, die Hermes für eine erwartete Gruppe sehen muss."""
    if group is None:
        return None
    return "block" if group in block_groups else "approve"


def main() -> int:
    ap = argparse.ArgumentParser()
    default = Path(__file__).resolve().parent.parent / "files/system/usr/share/hermes-os/plugins/hermes_os"
    ap.add_argument("--plugin-dir", type=Path, default=default)
    opts = ap.parse_args()
    b = load_boundary(opts.plugin_dir)

    fails = []
    for cmd, want in CASES:
        hit = b.classify_system_command(cmd)
        got = hit["group"] if hit else None
        if got != want:
            fails.append(f"{cmd!r}: Gruppe {got!r}, erwartet {want!r}" + (f" (Segment {hit['segment']!r})" if hit else ""))
            continue
        d = b.pre_tool_call_directive("terminal", {"command": cmd})
        if (d or {}).get("action") != expected_action(want, b.BLOCK_GROUPS):
            fails.append(f"{cmd!r}: Aktion {d!r}, erwartet {expected_action(want, b.BLOCK_GROUPS)!r}")
        elif d and d["action"] == "block" and not d.get("message"):
            fails.append(f"{cmd!r}: block ohne Meldung (Hermes ignoriert das)")
    asking = sum(1 for _, g in CASES if g)
    free = len(CASES) - asking

    # Andere Werkzeuge und leere Eingaben bleiben unberührt
    for tool, args in (("write_file", {"path": "/etc/x"}), ("terminal", {}), ("terminal", None),
                       ("terminal", {"command": ""}), ("terminal", {"command": 42})):
        if b.pre_tool_call_directive(tool, args) is not None:
            fails.append(f"{tool} {args!r}: sollte frei sein")

    # Fail-closed: scheitert die Prüfung im Plugin, fragt der Hook
    sys.path.insert(0, str(opts.plugin_dir.parent))
    try:
        import hermes_os  # noqa: E402
    except Exception as exc:  # pragma: no cover
        fails.append(f"Plugin-Paket lässt sich nicht laden: {exc}")
    else:
        orig = hermes_os.boundary.classify_system_command

        def boom(_cmd):
            raise RuntimeError("Test")
        hermes_os.boundary.classify_system_command = boom
        logging.disable(logging.WARNING)
        try:
            d = hermes_os._pre_tool_call("terminal", {"command": "ls"})
        finally:
            hermes_os.boundary.classify_system_command = orig
            logging.disable(logging.NOTSET)
        if not d or d.get("action") != "approve":
            fails.append(f"fail-closed: Hook lieferte {d!r} statt approve")
        d = hermes_os._pre_tool_call("terminal", {"command": "sudo reboot"})
        if not d or d.get("action") != "block":
            fails.append(f"Plugin-Hook: sudo reboot lieferte {d!r} statt block")

    if fails:
        print("boundary check FAILED:")
        for f in fails:
            print("  " + f)
        return 1
    print(f"boundary check ok: {len(CASES)} Fälle ({asking} fragen oder verweigert, {free} frei), fail-closed geprüft")
    return 0


if __name__ == "__main__":
    sys.exit(main())
