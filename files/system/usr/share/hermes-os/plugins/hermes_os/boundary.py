"""hermes-os -- die Grenze: welche Terminal-Befehle fragen, welche frei laufen.

Der ``pre_tool_call``-Hook des Plugins ruft :func:`pre_tool_call_directive`.
Grundlage ist :func:`classify_system_command`, ein Klassifikator über den
Befehlsstring des terminal-Werkzeugs. Er erkennt Befehle, keine Wirkungen:
Was ein Skript oder ein Interpreter im Inneren tut, sieht er nicht. Die
eigentliche Barriere gegen Systemänderungen ist, dass der Nutzer ohne
Passwort kein Root hat; der Hook sorgt dafür, dass der Agent fragt, bevor er
es versucht. Vertrag, Abdeckung und Restlücken: docs/grenze.md.

Aufbau:
1. ``_lex`` zerlegt den String wie eine Shell in einfache Befehle (Wörter,
   Umleitungen, Heredocs), beachtet Anführungszeichen, Escapes und
   Zeilenfortsetzungen und sammelt ``$(...)``, Backticks und ``<(...)``
   zum rekursiven Prüfen ein.
2. ``_analyze`` entschachtelt Hüllen (sudo, env, timeout, xargs, find -exec,
   sh -c, systemd-run, flatpak-spawn --host, nsenter, chroot ...) rekursiv
   und merkt sich, ob der Rest mit Root-Rechten liefe.
3. ``_leaf`` prüft den innersten Befehl gegen die Gruppen. Mit Root-Rechten
   fragt alles, was nicht auf der Allowlist reiner Lesebefehle steht.

Die Angriffsbatterie liegt in tests/boundary-check.py.
"""
from __future__ import annotations

import posixpath
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

# Gruppen, die nicht gefragt, sondern verweigert werden (Hook-Aktion "block").
BLOCK_GROUPS = frozenset({"power"})

# Schreibziele, die das laufende System berühren
SYSTEM_PREFIXES = ("/etc", "/usr", "/boot", "/var/lib", "/ostree", "/sysroot")

_MAX_DEPTH = 8
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh", "fish", "mksh", "tcsh", "csh"})
_ELEVATORS = frozenset({"sudo", "doas", "pkexec", "run0", "su", "sudoedit"})
_KEYWORDS = frozenset({"if", "then", "else", "elif", "fi", "do", "done", "while", "until",
                       "{", "}", "!", "esac"})
_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\[[^\]]*\])?\+?=")


class _Hit(Exception):
    """Trägt einen Treffer aus der Rekursion nach oben."""

    def __init__(self, group: str, segment: str, command: str = ""):
        super().__init__(group)
        self.group = group
        self.segment = segment
        self.command = command


# ---------------------------------------------------------------------------
# 1. Lexer
# ---------------------------------------------------------------------------

class _Simple:
    """Ein einfacher Befehl: Wörter, Umleitungen, Heredoc-Texte, Vorgänger."""

    __slots__ = ("words", "redirects", "heredocs", "herestrings", "piped_from", "text")

    def __init__(self) -> None:
        self.words: List[str] = []
        self.redirects: List[Tuple[str, str]] = []
        self.heredocs: List[str] = []
        self.herestrings: List[str] = []
        self.piped_from: Optional["_Simple"] = None
        self.text = ""


def _find_closing(s: str, i: int, open_ch: str, close_ch: str) -> int:
    """Index der schließenden Klammer ab Position i (i steht hinter der
    öffnenden), mit Verschachtelung und Anführungszeichen. -1 wenn offen."""
    depth = 1
    n = len(s)
    while i < n:
        c = s[i]
        if c == "\\":
            i += 2
            continue
        if c == "'":
            j = s.find("'", i + 1)
            if j < 0:
                return -1
            i = j + 1
            continue
        if c == '"':
            i += 1
            while i < n and s[i] != '"':
                i += 2 if s[i] == "\\" else 1
            i += 1
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return -1


def _lex(command: str, subs: List[str]) -> List[_Simple]:
    """Zerlegt ``command`` in einfache Befehle. Innere Befehle aus ``$(...)``,
    Backticks und Prozess-Substitution landen in ``subs``."""
    s = command.replace("\\\r\n", "").replace("\\\n", "")
    n = len(s)
    out: List[_Simple] = []
    cur = _Simple()
    word: List[str] = []
    in_word = False          # auch leere Wörter ('') zählen
    pending_redirect: Optional[str] = None
    pending_heredoc: List[Tuple[str, bool]] = []   # (Ende-Marke, Tabs entfernen)
    seg_start = 0
    pipe_next = False

    def end_word() -> None:
        nonlocal word, in_word, pending_redirect
        if not in_word:
            return
        w = "".join(word)
        word, in_word = [], False
        if pending_redirect is not None:
            op = pending_redirect
            pending_redirect = None
            if op in ("<<", "<<-"):
                pending_heredoc.append((w, op == "<<-"))
            elif op == "<<<":
                cur.herestrings.append(w)
            else:
                cur.redirects.append((op, w))
            return
        cur.words.append(w)

    def end_simple(end: int, pipe: bool) -> None:
        nonlocal cur, seg_start, pipe_next
        end_word()
        cur.text = s[seg_start:end].strip()
        if cur.words or cur.redirects or cur.heredocs or cur.herestrings:
            if pipe_next and out:
                cur.piped_from = out[-1]
            out.append(cur)
        cur = _Simple()
        seg_start = end
        pipe_next = pipe

    i = 0
    while i < n:
        c = s[i]
        if c in " \t\r\f\v":
            end_word()
            i += 1
            continue
        if c == "\n":
            end_simple(i, False)
            i += 1
            # Heredoc-Texte beginnen in der Zeile nach dem Operator
            while pending_heredoc:
                marker, strip_tabs = pending_heredoc.pop(0)
                body: List[str] = []
                while i < n:
                    j = s.find("\n", i)
                    line = s[i:] if j < 0 else s[i:j]
                    i = n if j < 0 else j + 1
                    check = line.lstrip("\t") if strip_tabs else line
                    if check == marker:
                        break
                    body.append(line)
                (out[-1] if out else cur).heredocs.append("\n".join(body))
            seg_start = i
            continue
        if c == "#" and not in_word:
            j = s.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "\\":
            if i + 1 < n:
                word.append(s[i + 1])
            in_word = True
            i += 2
            continue
        if c == "'":
            j = s.find("'", i + 1)
            j = n if j < 0 else j
            word.append(s[i + 1:j])
            in_word = True
            i = j + 1
            continue
        if c == "$" and s.startswith("$'", i):
            # ANSI-C-Quoting: Escapes grob auflösen
            j = i + 2
            buf: List[str] = []
            while j < n and s[j] != "'":
                if s[j] == "\\" and j + 1 < n:
                    esc = s[j + 1]
                    buf.append({"n": "\n", "t": "\t", "'": "'", "\\": "\\"}.get(esc, esc))
                    j += 2
                    continue
                buf.append(s[j])
                j += 1
            word.append("".join(buf))
            in_word = True
            i = j + 1
            continue
        if c == '"':
            j = i + 1
            buf = []
            while j < n and s[j] != '"':
                if s[j] == "\\" and j + 1 < n and s[j + 1] in '"\\$`\n':
                    if s[j + 1] != "\n":
                        buf.append(s[j + 1])
                    j += 2
                    continue
                if s.startswith("$(", j):
                    k = _find_closing(s, j + 2, "(", ")")
                    k = n if k < 0 else k
                    subs.append(s[j + 2:k])
                    buf.append("\x00")
                    j = k + 1
                    continue
                if s[j] == "`":
                    k = s.find("`", j + 1)
                    k = n if k < 0 else k
                    subs.append(s[j + 1:k])
                    buf.append("\x00")
                    j = k + 1
                    continue
                buf.append(s[j])
                j += 1
            word.append("".join(buf))
            in_word = True
            i = j + 1
            continue
        if s.startswith("$(", i):
            k = _find_closing(s, i + 2, "(", ")")
            k = n if k < 0 else k
            subs.append(s[i + 2:k])
            word.append("\x00")
            in_word = True
            i = k + 1
            continue
        if c == "`":
            k = s.find("`", i + 1)
            k = n if k < 0 else k
            subs.append(s[i + 1:k])
            word.append("\x00")
            in_word = True
            i = k + 1
            continue
        if c in "<>" and s.startswith("(", i + 1):
            k = _find_closing(s, i + 2, "(", ")")
            k = n if k < 0 else k
            subs.append(s[i + 2:k])
            word.append("\x00")
            in_word = True
            i = k + 1
            continue
        if c in ";&|()":
            two = s[i:i + 2]
            if two == "&>":
                end_word()
                op = "&>>" if s.startswith("&>>", i) else "&>"
                pending_redirect = op
                i += len(op)
                continue
            end_simple(i, two in ("|", "|&") or (c == "|" and two != "||"))
            i += 2 if two in ("&&", "||", ";;", "|&") else 1
            continue
        if c in "<>":
            # Dateideskriptor-Präfix (2>, 1>>) gehört nicht zum Wort davor
            if in_word and "".join(word).isdigit():
                word, in_word = [], False
            else:
                end_word()
            if s.startswith("<<<", i):
                op = "<<<"
            elif s.startswith("<<-", i):
                op = "<<-"
            elif s.startswith("<<", i):
                op = "<<"
            elif s.startswith(">>", i):
                op = ">>"
            elif s.startswith(">|", i) or s.startswith("<>", i):
                op = s[i:i + 2]
            else:
                op = c
            i += len(op)
            if op in (">", ">>", "<") and s.startswith("&", i):
                # 2>&1, >&-: Duplikat, kein Dateiziel
                i += 1
                while i < n and (s[i].isdigit() or s[i] == "-"):
                    i += 1
                continue
            pending_redirect = op
            continue
        word.append(c)
        in_word = True
        i += 1
    end_simple(n, False)
    return out


# ---------------------------------------------------------------------------
# 2. Hilfen
# ---------------------------------------------------------------------------

def _norm_path(p: str) -> str:
    p = p.strip()
    if not p.startswith("/"):
        return p
    p = "/" + p.lstrip("/")
    return posixpath.normpath(p)


def _is_system_path(p: str) -> bool:
    p = _norm_path(p)
    if not p.startswith("/"):
        return False
    if p == "/":
        return True
    return any(p == pre or p.startswith(pre + "/") for pre in SYSTEM_PREFIXES)


def _name(word: str) -> str:
    return posixpath.basename(word) if "/" in word else word


def _operands(args: List[str]) -> List[str]:
    """Wörter ohne Optionen (alles nach ``--`` zählt als Operand)."""
    out: List[str] = []
    dashdash = False
    for a in args:
        if not dashdash and a == "--":
            dashdash = True
            continue
        if not dashdash and a.startswith("-") and a != "-":
            continue
        out.append(a)
    return out


def _has_flag(args: List[str], short: str = "", long: Iterable[str] = ()) -> bool:
    for a in args:
        if a == "--":
            return False
        if a.startswith("--"):
            if any(a == f or a.startswith(f + "=") for f in long):
                return True
        elif short and a.startswith("-") and len(a) > 1 and any(ch in a[1:] for ch in short):
            return True
    return False


def _skip_options(args: List[str], with_value: Iterable[str] = (),
                  stop_at_operand: bool = True) -> List[str]:
    """Überspringt führende Optionen; Optionen in ``with_value`` nehmen das
    nächste Wort als Wert, wenn es nicht angehängt ist (-uroot, --user=x)."""
    with_value = set(with_value)
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return args[i + 1:]
        if not a.startswith("-") or a == "-":
            break
        if "=" in a and a.startswith("--"):
            i += 1
            continue
        if a in with_value:
            i += 2
            continue
        if not a.startswith("--"):
            # Kurzoptionen gebündelt: -iu root, -uroot, -n5
            for k, ch in enumerate(a[1:], start=1):
                if "-" + ch in with_value:
                    i += 1 if k < len(a) - 1 else 2
                    break
            else:
                i += 1
            continue
        i += 1
    return args[i:]


def _hit(group: str, argv: List[str]) -> _Hit:
    return _Hit(group, " ".join(argv)[:160], _name(argv[0]) if argv else "")


# ---------------------------------------------------------------------------
# 3. Blätter: Gruppen und Allowlist
# ---------------------------------------------------------------------------

_POWER_VERBS = frozenset({"reboot", "poweroff", "halt", "kexec", "soft-reboot", "switch-root",
                          "rescue", "emergency"})
_SLEEP_VERBS = frozenset({"suspend", "hibernate", "hybrid-sleep", "suspend-then-hibernate", "sleep"})
_SYSTEMCTL_MUTATING = frozenset({
    "start", "stop", "restart", "reload", "try-restart", "reload-or-restart", "try-reload-or-restart",
    "force-reload", "condrestart", "enable", "disable", "reenable", "preset", "preset-all", "mask",
    "unmask", "link", "revert", "isolate", "set-default", "daemon-reload", "daemon-reexec", "edit",
    "kill", "clean", "freeze", "thaw", "set-property", "bind", "mount-image", "add-wants",
    "add-requires", "set-environment", "unset-environment", "import-environment", "default",
})
_SYSTEMCTL_READONLY = frozenset({
    "status", "show", "cat", "help", "is-active", "is-enabled", "is-failed", "is-system-running",
    "get-default", "list-units", "list-unit-files", "list-sockets", "list-timers", "list-jobs",
    "list-dependencies", "list-machines", "list-automounts", "list-paths", "show-environment",
})
_BOOTC_MUTATING = frozenset({"upgrade", "update", "switch", "rollback", "install", "edit",
                             "usr-overlay", "usroverlay", "kargs"})
_RPMOSTREE_MUTATING = frozenset({
    "install", "uninstall", "override", "kargs", "rebase", "rollback", "deploy", "upgrade",
    "update", "reset", "initramfs", "initramfs-etc", "cleanup", "cancel", "apply-live",
    "usroverlay", "reload", "finalize-deployment",
})
# ujust-Rezepte ohne Systemwirkung: die eigenen (Nutzerdienst, Einrichtung,
# Diagnose) und reine Anzeigen. Alles andere fragt.
_UJUST_FREE = re.compile(r"^(hermes-[a-z0-9-]+|changelogs)$")
_UJUST_FREE_FLAGS = frozenset({"--list", "-l", "--summary", "--show", "-s", "--help", "-h",
                               "--version", "-V", "--evaluate", "--variables", "--dump"})
_UJUST_IMAGE = frozenset({"update", "upgrade", "update-system", "rollback", "rebase-helper",
                          "rollback-helper", "toggle-updates", "toggle-devmode", "devmode"})

_USERS_CMDS = frozenset({"useradd", "usermod", "userdel", "passwd", "chpasswd", "gpasswd",
                         "groupadd", "groupdel", "groupmod", "visudo", "vipw", "vigr", "chsh",
                         "chfn", "chage", "newusers", "authselect"})
_BOOT_CMDS = frozenset({"grubby", "grub2-mkconfig", "grub2-install", "grub2-set-default",
                        "grub2-reboot", "grub2-editenv", "grub2-setpassword", "dracut",
                        "kernel-install", "bootupctl", "mokutil"})
_DISK_CMDS = frozenset({"sfdisk", "sgdisk", "gdisk", "wipefs", "mkswap", "cryptsetup",
                        "lvm", "pvcreate", "vgcreate", "lvcreate", "pvremove", "vgremove", "lvremove",
                        "lvextend", "lvresize", "vgextend", "mdadm", "blkdiscard", "resize2fs",
                        "xfs_growfs", "tune2fs", "e2fsck", "fsck", "cfdisk"})
_KERNEL_CMDS = frozenset({"insmod", "rmmod"})
_SECURITY_CMDS = frozenset({"setenforce", "semanage", "setsebool", "semodule", "load_policy"})
_FIREWALL_CMDS = frozenset({"firewall-cmd", "firewall-offline-cmd", "nft", "iptables", "ip6tables",
                            "ufw", "iptables-restore", "ip6tables-restore", "ebtables"})
# Dateibefehle, bei denen jedes Operand-Ziel zählt
_FILE_ANY_OPERAND = frozenset({"tee", "rm", "rmdir", "unlink", "chmod", "chown", "chgrp", "chattr",
                               "setfacl", "setfattr", "truncate", "touch", "mkdir", "shred", "mknod",
                               "mkfifo", "patch", "chcon", "restorecon"})
# Dateibefehle, bei denen nur das Ziel (letzter Operand oder -t) zählt
_FILE_DEST = frozenset({"cp", "install", "ln", "rsync", "scp"})

_DBUS_TOOLS = frozenset({"busctl", "dbus-send", "gdbus", "qdbus", "qdbus6", "qdbus-qt6", "qdbus-qt5"})
_DBUS_POWER_RE = re.compile(
    r"(login1.*\b(PowerOff|Reboot|Halt|KExec|SoftReboot)\w*\b)"
    r"|(org\.kde\.(Shutdown|LogoutPrompt)\b.*\b(logoutAndReboot|logoutAndShutdown|promptReboot|promptShutDown)\b)"
    r"|(ksmserver\b.*\blogout\b\s*(\S+\s+)?[12]\b)", re.I)
_DBUS_SLEEP_RE = re.compile(r"login1.*\b(Suspend|Hibernate|HybridSleep|SuspendThenHibernate)\b", re.I)

# Allowlist: reine Lesebefehle, die auch mit sudo/pkexec/doas/run0 frei bleiben
_READONLY_CMDS = frozenset({
    "cat", "less", "more", "head", "tail", "grep", "egrep", "fgrep", "zgrep", "wc", "file",
    "stat", "ls", "ll", "tree", "lsblk", "lspci", "lsusb", "lsmod", "lscpu", "lshw", "lsof",
    "lsinitrd", "lslogins", "findmnt", "df", "du", "free", "uptime", "id", "whoami", "groups",
    "uname", "hostname", "blkid", "diff", "cmp", "md5sum", "sha1sum", "sha256sum", "sha512sum",
    "strings", "hexdump", "od", "readlink", "realpath", "getfacl", "getfattr", "lsattr",
    "getenforce", "sestatus", "ausearch", "aureport", "pvs", "vgs", "lvs", "pvdisplay",
    "vgdisplay", "lvdisplay", "ss", "netstat", "dmidecode", "sensors", "nvidia-smi", "echo",
    "printf", "true", "test", "[", "printenv", "which", "type", "last", "lastlog", "who", "w",
    "ps", "pgrep", "sort", "uniq", "cut", "jq", "column", "zcat", "xzcat", "bzcat",
})


def _systemctl_verb(args: List[str]) -> Tuple[str, bool]:
    """(Verb, Nutzerbereich) für systemctl."""
    ops = _operands(_skip_options_anywhere(args, {"-t", "--type", "-p", "--property", "-M", "--machine",
                                                  "-H", "--host", "-n", "--lines", "-o", "--output",
                                                  "-s", "--signal", "--state", "--kill-whom",
                                                  "--what", "--root", "--job-mode", "--boot-loader-entry",
                                                  "--boot-loader-menu", "--timestamp", "--image",
                                                  "--drop-in", "--when", "--kill-value", "--reboot-argument",
                                                  "--message", "--preset-mode", "--check-inhibitors"}))
    user = "--user" in args and not any(a in args for a in ("--system", "--global"))
    return (ops[0] if ops else ""), user


def _skip_options_anywhere(args: List[str], with_value: Iterable[str]) -> List[str]:
    """Entfernt Optionen samt Werten an beliebiger Stelle."""
    with_value = set(with_value)
    out: List[str] = []
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            out.extend(args[i:])
            break
        if a.startswith("-") and a != "-":
            if a in with_value:
                i += 2
                continue
            i += 1
            continue
        out.append(a)
        i += 1
    return out


def _nmcli_mutating(args: List[str]) -> bool:
    ops = _skip_options_anywhere(args, {"-f", "--fields", "-g", "--get-values", "-e", "--escape",
                                         "-c", "--colors", "-m", "--mode", "-w", "--wait"})
    if not ops:
        return False
    obj, rest = ops[0], ops[1:]
    verb = rest[0] if rest else ""
    if "general".startswith(obj) or obj == "g":
        return verb in ("hostname", "logging", "reload") and len(rest) > 1 or verb == "reload"
    if "networking".startswith(obj) or obj == "n":
        return verb in ("on", "off")
    if "radio".startswith(obj) or obj == "r":
        return len(rest) >= 2 and rest[-1] in ("on", "off")
    if "connection".startswith(obj) or obj == "c":
        return verb not in ("", "show", "s", "sh", "monitor")
    if "device".startswith(obj) or obj == "d":
        if verb in ("", "status", "show", "s", "sh", "monitor", "lldp"):
            return False
        if verb in ("wifi", "w"):
            return len(rest) > 1 and rest[1] not in ("list", "l", "rescan", "show-password")
        return True
    if "agent".startswith(obj) or "monitor".startswith(obj) or "help".startswith(obj):
        return False
    return False


def _firewall_readonly(name: str, args: List[str]) -> bool:
    if name in ("firewall-cmd", "firewall-offline-cmd"):
        flags = [a for a in args if a.startswith("-")]
        ok = re.compile(r"^--(state|list-[\w-]+|get-[\w-]+|query-[\w-]+|info-[\w-]+|zone=.*|"
                        r"permanent|help|version|check-config)$|^-[hV]$")
        return bool(flags) and all(ok.match(f) for f in flags)
    if name == "nft":
        ops = _operands(args)
        return bool(ops) and ops[0] in ("list", "describe", "monitor")
    if name in ("iptables", "ip6tables"):
        return _has_flag(args, "LS", ("--list", "--list-rules")) and not _has_flag(
            args, "AIDRFXPNZE", ("--append", "--insert", "--delete", "--replace", "--flush",
                                 "--delete-chain", "--policy", "--new-chain", "--zero", "--rename-chain"))
    return False


def _power_or_sleep(name: str, args: List[str]) -> Optional[str]:
    if name in ("reboot", "poweroff", "halt", "kexec"):
        return "power"
    if name == "shutdown":
        return None if _has_flag(args, "c", ("--show",)) else "power"
    if name in ("init", "telinit"):
        ops = _operands(args)
        return "power" if ops and ops[0] in ("0", "6", "1", "s", "S", "single") else None
    if name == "systemctl":
        verb, _user = _systemctl_verb(args)
        if verb in _POWER_VERBS:
            return "power"
        if verb in _SLEEP_VERBS:
            return "sleep"
    if name == "loginctl":
        ops = _operands(args)
        verb = ops[0] if ops else ""
        if verb in ("poweroff", "reboot", "halt", "kexec", "soft-reboot"):
            return "power"
        if verb in _SLEEP_VERBS:
            return "sleep"
    if name in ("systemd-hibernate", "pm-suspend", "pm-hibernate", "rtcwake"):
        return "sleep"
    if name in _DBUS_TOOLS:
        joined = " ".join(args)
        if _DBUS_POWER_RE.search(joined):
            return "power"
        if _DBUS_SLEEP_RE.search(joined):
            return "sleep"
    return None


def _file_targets(name: str, args: List[str]) -> List[str]:
    """Pfade, auf die ein Dateibefehl schreibt oder die er verändert."""
    if name in _FILE_ANY_OPERAND:
        return _operands(args)
    if name == "mv":
        return _operands(args)       # Quelle verschwindet, Ziel entsteht
    if name in _FILE_DEST:
        for i, a in enumerate(args):
            if a in ("-t", "--target-directory") and i + 1 < len(args):
                return [args[i + 1]]
            if a.startswith("--target-directory="):
                return [a.split("=", 1)[1]]
        ops = _operands(args)
        if name == "ln":
            return ops[-1:] if len(ops) >= 2 else []
        return ops[-1:] if len(ops) >= 2 else ops
    if name == "sed":
        if not _has_flag(args, "i", ("--in-place",)):
            return []
        ops = _operands(args)
        return ops if _has_flag(args, "ef", ("--expression", "--file")) else ops[1:]
    if name in ("perl", "ruby"):
        pre = args[:len(args) - len(_skip_options(args, ("-e", "-E", "-I", "-M")))]
        if any(not a.startswith("--") and a.startswith("-") and "i" in a[1:].split(".")[0] for a in pre):
            return _operands(args)
        return []
    if name == "dd":
        return [a[3:] for a in args if a.startswith("of=")]
    if name in _OUTPUT_FLAGS:
        out: List[str] = []
        for i, a in enumerate(args):
            for f in _OUTPUT_FLAGS[name]:
                if a == f and i + 1 < len(args):
                    out.append(args[i + 1])
                elif f.startswith("--") and a.startswith(f + "="):
                    out.append(a.split("=", 1)[1])
                elif not f.startswith("--") and a.startswith(f) and len(a) > len(f):
                    out.append(a[len(f):])
        if name in ("tar", "bsdtar") and not _tar_extracts(args):
            return []
        return out
    if name == "find":
        writes = [args[i + 1] for i, a in enumerate(args)
                  if a in ("-fprint", "-fprint0", "-fprintf", "-fls") and i + 1 < len(args)]
        if "-delete" in args or writes:
            starts = []
            for a in args:
                if a.startswith(("-", "(", "!")):
                    break
                starts.append(a)
            return starts + writes
        return []
    return []


_OUTPUT_FLAGS = {
    "curl": ("-o", "--output", "--output-dir"),
    "wget": ("-O", "--output-document", "-P", "--directory-prefix"),
    "sort": ("-o", "--output"),
    "tar": ("-C", "--directory"), "bsdtar": ("-C", "--directory"),
    "unzip": ("-d",), "cpio": ("-D", "--directory"),
}


def _tar_extracts(args: List[str]) -> bool:
    for a in args:
        if a in ("-x", "--extract", "--get") or (not a.startswith("--") and a.startswith("-") and "x" in a):
            return True
    return bool(args) and not args[0].startswith("-") and "x" in args[0]


def _readonly(name: str, args: List[str]) -> bool:
    """Reiner Lesebefehl, der auch mit Root-Rechten frei bleibt."""
    if name == "journalctl":
        return not any(a.startswith(("--vacuum", "--rotate", "--flush", "--relinquish-var", "--sync",
                                     "--setup-keys", "--update-catalog", "--smart-relinquish-var"))
                       for a in args)
    if name == "dmesg":
        return not _has_flag(args, "cCDEn", ("--clear", "--read-clear", "--console-off",
                                             "--console-on", "--console-level"))
    if name == "systemctl":
        verb, _user = _systemctl_verb(args)
        return verb in _SYSTEMCTL_READONLY or verb.startswith("list-") or verb == ""
    if name == "bootc":
        ops = _operands(args)
        return bool(ops) and ops[0] == "status"
    if name == "rpm-ostree":
        ops = _operands(args)
        return bool(ops) and (ops[0] == "status" or ops[:2] in (["db", "diff"], ["db", "list"]))
    if name == "ostree":
        ops = _operands(args)
        return ops[:2] == ["admin", "status"] or (bool(ops) and ops[0] in ("log", "show", "refs", "ls", "cat"))
    if name == "nmcli":
        return not _nmcli_mutating(args)
    if name in _FIREWALL_CMDS:
        return _firewall_readonly(name, args)
    if name == "ip":
        ops = _operands(args)
        return not any(v in ops for v in ("add", "del", "delete", "set", "change", "replace", "flush",
                                          "append", "prepend", "exec", "attach", "detach", "save",
                                          "restore", "pids"))
    if name in ("timedatectl", "localectl", "hostnamectl", "resolvectl"):
        ops = _operands(args)
        return not ops or ops[0] in ("status", "show", "list-timezones", "list-locales",
                                     "list-keymaps", "list-x11-keymap-models", "list-x11-keymap-layouts",
                                     "list-x11-keymap-variants", "list-x11-keymap-options", "query",
                                     "statistics", "timesync-status", "show-timesync")
    if name == "loginctl":
        ops = _operands(args)
        return not ops or ops[0].startswith(("list-", "show-", "session-status", "user-status", "seat-status"))
    if name in ("fdisk", "sfdisk", "parted"):
        return _has_flag(args, "l", ("--list",)) or (name == "parted" and "print" in args)
    if name == "efibootmgr":
        return all(a in ("-v", "--verbose") for a in args)
    if name == "bootctl":
        ops = _operands(args)
        return not ops or ops[0] in ("status", "list", "is-installed")
    if name == "cryptsetup":
        ops = _operands(args)
        return bool(ops) and ops[0] in ("status", "luksDump", "isLuks")
    if name == "flatpak":
        ops = _operands(args)
        return bool(ops) and ops[0] in ("list", "info", "remotes", "history", "search", "ps")
    if name == "find":
        return not _file_targets(name, args)
    if name == "hostname":
        return not _operands(args)
    if name == "fwupdmgr":
        ops = _operands(args)
        return not ops or ops[0].startswith("get-")
    if name == "sort":
        return not _file_targets(name, args)
    if name in ("date",):
        return not _has_flag(args, "s", ("--set",))
    return name in _READONLY_CMDS


def _leaf(argv: List[str], elevated: bool) -> None:
    """Prüft einen innersten Befehl; wirft _Hit bei einem Treffer."""
    name = _name(argv[0])
    args = argv[1:]

    grp = _power_or_sleep(name, args)
    if grp:
        raise _hit(grp, argv)

    if name == "bootc":
        ops = _operands(args)
        if ops and ops[0] in _BOOTC_MUTATING:
            raise _hit("boot" if ops[0] == "kargs" else "image", argv)
    elif name == "rpm-ostree":
        ops = _operands(args)
        if ops and ops[0] in _RPMOSTREE_MUTATING:
            raise _hit("image", argv)
    elif name == "ostree":
        ops = _operands(args)
        if ops[:1] == ["admin"] and ops[1:2] != ["status"]:
            raise _hit("image", argv)
        if ops[:1] == ["remote"] and len(ops) > 1 and ops[1] in ("add", "delete", "gpg-import") \
                and not any(a.startswith("--repo") for a in args):
            raise _hit("image", argv)
    elif name in ("systemd-sysext", "systemd-confext"):
        ops = _operands(args)
        if ops and ops[0] in ("merge", "unmerge", "refresh"):
            raise _hit("image", argv)
    elif name == "ujust":
        ops = _operands(args)
        if not ops or any(a in _UJUST_FREE_FLAGS for a in args):
            return
        if ops[0] in _UJUST_IMAGE:
            raise _hit("image", argv)
        if not _UJUST_FREE.match(ops[0]):
            raise _hit("ujust", argv)
    elif name == "systemctl":
        verb, user = _systemctl_verb(args)
        if verb in _SYSTEMCTL_MUTATING and not user:
            raise _hit("services", argv)
    elif name in ("init", "telinit"):
        if _operands(args):
            raise _hit("services", argv)     # Runlevel-Wechsel beendet die Sitzung
    elif name in ("service", "chkconfig"):
        if len(_operands(args)) >= 2 or name == "chkconfig" and _operands(args):
            raise _hit("services", argv)
    elif name == "loginctl":
        ops = _operands(args)
        verb = ops[0] if ops else ""
        if verb.startswith(("terminate-", "kill-")):
            raise _hit("session", argv)
        if verb in ("enable-linger", "disable-linger", "attach", "flush-devices"):
            raise _hit("system-config", argv)
    elif name == "systemd-run":
        if "--user" not in args:
            raise _hit("services", argv)
    elif name == "machinectl":
        ops = _operands(_skip_options_anywhere(args, {"-M", "--machine", "-H", "--host", "-p",
                                                      "--property", "--uid", "-E", "--setenv"}))
        verb = ops[0] if ops else "list"
        if verb not in ("list", "status", "show", "list-images", "image-status", "show-image",
                        "list-transfers"):
            raise _hit("services", argv)
    elif name in _FIREWALL_CMDS:
        if not _firewall_readonly(name, args):
            raise _hit("network", argv)
    elif name == "nmcli":
        if _nmcli_mutating(args):
            raise _hit("network", argv)
    elif name in _USERS_CMDS:
        if not (name == "authselect" and _operands(args)[:1] in (["current"], ["list"], ["check"])):
            raise _hit("users", argv)
    elif name in _BOOT_CMDS:
        if not (name == "mokutil" and all(a in ("--sb-state", "--list-enrolled", "-l", "--list-new",
                                                  "--test-key", "-t") or not a.startswith("-") for a in args)
                or name == "grub2-editenv" and "list" in args):
            raise _hit("boot", argv)
    elif name == "bootctl":
        if not _readonly(name, args):
            raise _hit("boot", argv)
    elif name == "efibootmgr":
        if not _readonly(name, args):
            raise _hit("boot", argv)
    elif name in ("sysctl",):
        if _has_flag(args, "wp", ("--write", "--load", "--system")) or any("=" in a for a in _operands(args)):
            raise _hit("system-config", argv)
    elif name in ("localectl", "timedatectl", "hostnamectl"):
        ops = _operands(args)
        if ops and (ops[0].startswith("set-") or ops[0] in ("hostname", "icon-name", "chassis",
                                                            "deployment", "location", "ntp-servers",
                                                            "revert")
                    and (len(ops) > 1 or ops[0] == "revert")):
            raise _hit("system-config", argv)
    elif name == "hostname":
        if _operands(args) or _has_flag(args, "F", ("--file",)):
            raise _hit("system-config", argv)
    elif name in ("date",):
        if _has_flag(args, "s", ("--set",)):
            raise _hit("system-config", argv)
    elif name == "hwclock":
        if _has_flag(args, "w", ("--systohc", "--set", "--hctosys", "--adjust")) or "-s" in args:
            raise _hit("system-config", argv)
    elif name in ("ssh-keygen", "ssh-copy-id"):
        if not (name == "ssh-keygen" and _has_flag(args, "lFyB", ())):
            raise _hit("ssh", argv)
    elif name in ("fdisk", "parted", "mkfs") or name.startswith("mkfs.") or name in _DISK_CMDS:
        if not _readonly(name, args):
            raise _hit("disks", argv)
    elif name in ("mount", "umount", "losetup", "swapon", "swapoff"):
        if _operands(args) or _has_flag(args, "a", ("--all",)):
            raise _hit("disks", argv)
    elif name == "dd":
        for a in args:
            if a.startswith("of=/dev/") and a[3:] not in ("/dev/null", "/dev/stdout", "/dev/stderr"):
                raise _hit("disks", argv)
    elif name in ("modprobe",):
        if not _has_flag(args, "nc", ("--dry-run", "--show-depends", "--showconfig", "--show")):
            raise _hit("kernel", argv)
    elif name in _KERNEL_CMDS:
        raise _hit("kernel", argv)
    elif name in _SECURITY_CMDS:
        raise _hit("security", argv)
    elif name == "flatpak":
        ops = _operands(args)
        if ops and ops[0] in ("install", "remove", "uninstall", "update", "upgrade", "override",
                              "repair", "remote-add", "remote-delete", "remote-modify", "mask", "pin") \
                and _has_flag(args, "", ("--system", "--installation")):
            raise _hit("flatpak-system", argv)
    elif name in ("distrobox", "distrobox-create", "distrobox-enter", "distrobox-rm"):
        if _has_flag(args, "r", ("--root",)):
            raise _hit("sudo", argv)

    for p in _file_targets(name, args):
        if _is_system_path(p):
            raise _hit("system-files", argv)

    if elevated and not _readonly(name, args):
        raise _hit("sudo", argv)


# ---------------------------------------------------------------------------
# 4. Hüllen entschachteln
# ---------------------------------------------------------------------------

_SUDO_VALUE_OPTS = {"-u", "--user", "-g", "--group", "-C", "--close-from", "-D", "--chdir",
                    "-h", "--host", "-p", "--prompt", "-r", "--role", "-t", "--type", "-U",
                    "--other-user", "-T", "--command-timeout", "-R", "--chroot"}
_RUN0_VALUE_OPTS = {"-u", "--user", "-g", "--group", "-D", "--chdir", "--unit", "--property",
                    "-p", "--description", "--slice", "--slice-inherit", "--nice", "--setenv",
                    "--background", "--machine", "--area", "--via-shell"}


def _shell_script(args: List[str]) -> Tuple[Optional[str], bool]:
    """Für sh/bash: (Skripttext bei -c, liest es eine Datei/stdin?)"""
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--":
            return None, i + 1 < len(args)
        if a.startswith("-") and not a.startswith("--") and len(a) > 1:
            if "c" in a[1:]:
                return (args[i + 1] if i + 1 < len(args) else ""), False
            if a[1:] in ("o", "O") and i + 1 < len(args):
                i += 2
                continue
            i += 1
            continue
        if a.startswith("+") or a.startswith("--"):
            if a in ("--rcfile", "--init-file") and i + 1 < len(args):
                i += 2
                continue
            i += 1
            continue
        return None, True     # Skriptdatei als Operand
    return None, False


def _analyze(argv: List[str], simple: Optional[_Simple], elevated: bool, depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise _hit("nesting", argv)
    # Zuweisungen und Schlüsselwörter vorne entfernen
    while argv and (_ASSIGN_RE.match(argv[0]) or argv[0] in _KEYWORDS):
        argv = argv[1:]
    if not argv:
        return
    name = _name(argv[0])
    args = argv[1:]
    nxt = depth + 1

    # --- Rechte erhöhen ------------------------------------------------------
    if name in _ELEVATORS:
        if name == "sudoedit":
            raise _hit("system-files", argv)
        if name == "sudo":
            rest = _skip_options(args, _SUDO_VALUE_OPTS)
            opts = args[:len(args) - len(rest)]
            if _has_flag(opts, "e", ("--edit",)):
                raise _hit("system-files", argv)
            if not rest and opts and all(a in ("-l", "-ll", "--list", "-v", "--validate", "-k", "-K",
                                               "--reset-timestamp", "--remove-timestamp", "-V",
                                               "--version", "-h", "--help", "-n", "--non-interactive")
                                         for a in opts):
                return
            if not rest:
                raise _hit("root-shell", argv)
            if _has_flag(opts, "is", ("--login", "--shell")):
                _classify_text(" ".join(rest), elevated=True, depth=nxt)
                return
        elif name == "doas":
            rest = _skip_options(args, {"-u", "-C"})
            if not rest or "-s" in args[:len(args) - len(rest)]:
                raise _hit("root-shell", argv)
        elif name == "pkexec":
            rest = _skip_options(args, {"--user", "-u"})
            if not rest:
                raise _hit("root-shell", argv)
        elif name == "run0":
            rest = _skip_options(args, _RUN0_VALUE_OPTS)
            if not rest:
                raise _hit("root-shell", argv)
        else:   # su
            cmd = None
            i = 0
            while i < len(args):
                a = args[i]
                if a in ("-c", "--command") and i + 1 < len(args):
                    cmd = args[i + 1]
                    i += 2
                    continue
                if a.startswith("--command="):
                    cmd = a.split("=", 1)[1]
                i += 1
            if cmd is None:
                raise _hit("root-shell", argv)
            _classify_text(cmd, elevated=True, depth=nxt)
            return
        _analyze(rest, None, True, nxt)
        return

    # --- Shells ----------------------------------------------------------------
    if name in _SHELLS:
        script, reads_file = _shell_script(args)
        if script is not None:
            _classify_text(script, elevated=elevated, depth=nxt)
            return
        if elevated and not reads_file:
            raise _hit("root-shell", argv)
        if elevated:
            raise _hit("sudo", argv)
        # Text, der in eine Shell fließt: Heredoc, Here-String, echo | sh
        if simple is not None and not reads_file:
            for body in simple.heredocs + simple.herestrings:
                _classify_text(body, elevated=False, depth=nxt)
            src = simple.piped_from
            if src is not None and src.words and _name(src.words[0]) in ("echo", "printf"):
                _classify_text(" ".join(_operands(src.words[1:])).replace("\\n", "\n"),
                               elevated=False, depth=nxt)
        return
    if name == "eval":
        _classify_text(" ".join(args), elevated=elevated, depth=nxt)
        return

    # --- Hüllen, die einen Befehl ausführen ------------------------------------
    rest: Optional[List[str]] = None
    if name == "env":
        i = 0
        while i < len(args):
            a = args[i]
            if a in ("-u", "--unset", "-C", "--chdir") and i + 1 < len(args):
                i += 2
                continue
            if a in ("-S", "--split-string") and i + 1 < len(args):
                rest = args[i + 1].split() + args[i + 2:]
                break
            if a.startswith("--split-string="):
                rest = a.split("=", 1)[1].split() + args[i + 1:]
                break
            if a.startswith("-") and a != "-" or _ASSIGN_RE.match(a):
                i += 1
                continue
            rest = args[i:]
            break
    elif name in ("nice",):
        rest = _skip_options(args, {"-n", "--adjustment"})
    elif name in ("nohup", "exec", "builtin", "unbuffer", "catchsegv", "setpriv", "firejail",
                  "flock", "stdbuf", "ionice", "setsid", "chrt", "taskset", "caffeinate",
                  "systemd-inhibit", "doit"):
        if name == "exec":
            rest = _skip_options(args, {"-a"})
        elif name == "stdbuf":
            rest = _skip_options(args, {"-i", "-o", "-e"})
        elif name == "ionice":
            rest = _skip_options(args, {"-c", "-n", "-p", "-P", "-u", "--class", "--classdata"})
        elif name == "chrt":
            r = _skip_options(args, {"-T", "-P", "-D"})
            rest = r[1:] if r and r[0].isdigit() else r
        elif name == "taskset":
            r = _skip_options(args, ())
            rest = r[1:] if r else r
        elif name == "flock":
            r = _skip_options(args, {"-w", "--timeout", "-E", "--conflict-exit-code"})
            if r and r[1:2] in (["-c"], ["--command"]):
                _classify_text(r[2] if len(r) > 2 else "", elevated=elevated, depth=nxt)
                return
            rest = r[1:] if r else r
        elif name == "systemd-inhibit":
            rest = _skip_options(args, {"--what", "--who", "--why", "--mode"})
        elif name == "setpriv":
            rest = _skip_options(args, {"--reuid", "--regid", "--groups", "--inh-caps", "--ambient-caps",
                                        "--bounding-set", "--securebits", "--selinux-label",
                                        "--apparmor-profile", "--pdeathsig"})
        elif name == "firejail":
            rest = _skip_options(args, ())
        else:
            rest = _skip_options(args, ())
    elif name == "busybox":
        rest = args
    elif name == "command":
        if _has_flag(args, "vV", ()):
            return
        rest = _skip_options(args, ())
    elif name == "time":
        rest = _skip_options(args, {"-f", "--format", "-o", "--output"})
    elif name == "timeout":
        r = _skip_options(args, {"-s", "--signal", "-k", "--kill-after"})
        rest = r[1:] if r else r
    elif name == "watch":
        r = _skip_options(args, {"-n", "--interval", "-d", "-q", "--equexit"})
        _classify_text(" ".join(r), elevated=elevated, depth=nxt)
        return
    elif name == "xargs":
        rest = _skip_options(args, {"-a", "--arg-file", "-d", "--delimiter", "-E", "-e", "-I", "-i",
                                    "-L", "-l", "-n", "--max-args", "-P", "--max-procs", "-s",
                                    "--max-chars", "--process-slot-var"})
    elif name == "find":
        for i, a in enumerate(args):
            if a in ("-exec", "-execdir", "-ok", "-okdir"):
                sub: List[str] = []
                for b in args[i + 1:]:
                    if b in (";", "+"):
                        break
                    sub.append(b)
                if sub:
                    _analyze(sub, None, elevated, nxt)
        _leaf(argv, elevated)
        return
    elif name in ("flatpak-spawn",):
        rest = _skip_options(args, ())
        if "--host" not in args:
            rest = None     # läuft in der Flatpak-Sandbox
    elif name in ("distrobox-host-exec", "host-spawn"):
        rest = _skip_options(args, ())
    elif name == "toolbox":
        # toolbox run läuft im Container; nur eine Host-Hülle zählt
        ops = _skip_options_anywhere(args, {"-c", "--container", "-d", "--distro", "-r", "--release"})
        if ops[:1] == ["run"] and "--host" in args:
            rest = ops[1:]
    elif name == "nsenter":
        rest = _skip_options(args, {"-t", "--target", "-S", "--setuid", "-G", "--setgid",
                                    "-w", "--wd", "-r", "--root", "-W", "--wdns", "-N", "--net-socket"})
        if not rest:
            if elevated:
                raise _hit("root-shell", argv)
            return
    elif name == "chroot":
        r = _skip_options(args, {"--userspec", "--groups"})
        rest = r[1:] if r else r
        if not rest:
            if elevated:
                raise _hit("root-shell", argv)
            return
    elif name == "machinectl":
        ops = _skip_options_anywhere(args, {"-M", "--machine", "-H", "--host", "-p", "--property",
                                            "--uid", "-E", "--setenv"})
        if ops[:1] in (["shell"], ["login"]):
            # Anmeldung über polkit wie sudo, Nutzer ohne Angabe ist root
            if len(ops) <= 2:
                raise _hit("root-shell", argv)
            _analyze(ops[2:], None, True, nxt)
            return
    elif name == "systemd-run":
        if "--user" not in args:
            raise _hit("services", argv)
        rest = _skip_options(args, {"-p", "--property", "-u", "--unit", "-E", "--setenv",
                                    "--description", "--slice", "--uid", "--gid", "--nice",
                                    "-D", "--working-directory", "--on-active", "--on-boot",
                                    "--on-startup", "--on-unit-active", "--on-unit-inactive",
                                    "--on-calendar", "--on-timezone-change", "--on-clock-change",
                                    "--timer-property", "--path-property", "--socket-property",
                                    "-M", "--machine", "-H", "--host", "--service-type"})

    if rest is not None:
        if rest:
            _analyze(rest, simple, elevated, nxt)
        return

    _leaf(argv, elevated)


def _classify_text(text: str, elevated: bool, depth: int) -> None:
    if depth > _MAX_DEPTH:
        raise _Hit("nesting", text[:160], "")
    subs: List[str] = []
    simples = _lex(text, subs)
    for sub in subs:
        _classify_text(sub, elevated=False, depth=depth + 1)
    for simple in simples:
        for op, target in simple.redirects:
            if op in (">", ">>", ">|", "&>", "&>>", "<>") and _is_system_path(target):
                raise _Hit("system-files", simple.text[:160], simple.words[0] if simple.words else "")
        if simple.words:
            _analyze([w.replace("\x00", "") for w in simple.words], simple, elevated, depth)


# ---------------------------------------------------------------------------
# 5. Öffentliche Schnittstelle
# ---------------------------------------------------------------------------

def classify_system_command(command: str) -> Optional[Dict[str, str]]:
    """Gibt {'group', 'segment', 'command'} zurück, wenn der Befehl das
    laufende System berührt, sonst None. Reine Lesebefehle, alles im Home und
    alles mit --user bleiben frei."""
    if not isinstance(command, str) or not command.strip():
        return None
    try:
        _classify_text(command, elevated=False, depth=0)
    except _Hit as hit:
        return {"group": hit.group, "segment": hit.segment, "command": hit.command}
    return None


_GROUP_TEXT = {
    "power": "würde den Rechner neu starten oder ausschalten",
    "sleep": "würde den Rechner in den Ruhezustand schicken",
    "root-shell": "öffnet eine Root-Shell",
    "sudo": "läuft mit Root-Rechten",
    "image": "ändert das System-Image",
    "services": "steuert Systemdienste",
    "network": "ändert Firewall oder Netzwerk",
    "users": "ändert Nutzer oder Passwörter",
    "boot": "ändert Bootloader oder Kernel-Argumente",
    "ssh": "erzeugt oder verteilt SSH-Schlüssel",
    "disks": "berührt Datenträger oder Partitionen",
    "system-files": "schreibt unter /etc, /usr, /boot, /var/lib oder /ostree",
    "flatpak-system": "ändert die systemweite Flatpak-Installation",
    "system-config": "ändert systemweite Einstellungen",
    "session": "beendet Sitzungen",
    "kernel": "lädt oder entfernt Kernel-Module",
    "security": "ändert SELinux",
    "ujust": "startet ein ujust-Rezept mit möglicher Systemwirkung",
    "nesting": "ist zu tief verschachtelt, um ihn zu prüfen",
}


def directive_for(hit: Dict[str, str]) -> Dict[str, str]:
    """Hook-Antwort für einen Treffer: block für BLOCK_GROUPS, sonst approve."""
    group = hit["group"]
    seg = hit["segment"][:120]
    what = _GROUP_TEXT.get(group, "berührt das laufende System")
    if group in BLOCK_GROUPS:
        return {
            "action": "block",
            "message": (f"hermes-os: `{seg}` {what} ({group}). Das führt der Agent nie selbst aus. "
                        "Bitte den Nutzer, es selbst zu tun."),
        }
    rule = f"hermes-os:{group}"
    if hit.get("command"):
        rule += f":{hit['command']}"
    return {
        "action": "approve",
        "message": f"hermes-os: `{seg}` {what} ({group}). Freigabe nötig.",
        "rule_key": rule,
    }


def pre_tool_call_directive(tool_name: str, args: Any) -> Optional[Dict[str, str]]:
    """Antwort des Hooks für einen Werkzeugaufruf, None = frei."""
    if tool_name != "terminal" or not isinstance(args, dict):
        return None
    hit = classify_system_command(str(args.get("command") or ""))
    return directive_for(hit) if hit else None


def fail_closed_directive(exc: BaseException) -> Dict[str, str]:
    """Wenn die Prüfung selbst scheitert: fragen statt durchwinken."""
    return {
        "action": "approve",
        "message": (f"hermes-os: Die Grenzprüfung ist fehlgeschlagen ({type(exc).__name__}). "
                    "Freigabe nötig, weil nicht feststeht, ob der Befehl das System berührt."),
        "rule_key": "hermes-os:hook-error",
    }
