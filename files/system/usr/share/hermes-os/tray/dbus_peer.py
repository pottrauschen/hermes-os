"""hermes-os -- kleine D-Bus-Anbindung für den KRunner-Runner, nur Standardbibliothek.

Warum nicht QtDBus: KRunner erwartet von Match die Signatur a(sssida{sv}), ein
Feld von Strukturen. QtDBus kann das aus Python nicht bauen; QDBusArgument.
beginArray braucht einen mit qDBusRegisterMetaType angemeldeten C++-Typ für das
Element, den PySide6 nicht anbietet (Versuch mit PySide6 6.11: "type ... is not
registered with D-Bus", libdbus bricht bei falschem Elementtyp mit abort() ab).
dbus-python und PyGObject sind im Image nicht zugesagt. Das Protokoll selbst ist
klein: Anmeldung per EXTERNAL, Hello, RequestName, danach Nachrichten im
Drahtformat lesen und beantworten. Diese Datei kann genau so viel.

Der Aufrufer hängt fileno() an seine Ereignisschleife (QSocketNotifier im
Leisten-Symbol, select() im Test) und ruft read_ready(), sobald Daten da sind.
Ankommende Methodenaufrufe gehen an handler(message) -> (signature, body) oder
DBusError; der Rückgabewert wird zur Antwort. Signale (etwa von KGlobalAccel
für Push-to-Talk, tray/desktop.py) landen bei subscribe()-Rückrufen, nachdem
add_match() den Bus um sie gebeten hat.

Unterstützte Typen: y b n q i u x t d s o g a ( ) { } v, Byte-Reihenfolge beim
Senden immer little endian, beim Lesen beide.
"""
from __future__ import annotations

import os
import socket
import struct
from typing import Any, Callable, Dict, List, Optional, Tuple

METHOD_CALL, METHOD_RETURN, ERROR, SIGNAL = 1, 2, 3, 4
FLAG_NO_REPLY_EXPECTED = 0x1
# Kopffelder
F_PATH, F_INTERFACE, F_MEMBER, F_ERROR_NAME, F_REPLY_SERIAL, F_DESTINATION, F_SENDER, F_SIGNATURE = range(1, 9)
FIELD_TYPE = {F_PATH: "o", F_INTERFACE: "s", F_MEMBER: "s", F_ERROR_NAME: "s", F_REPLY_SERIAL: "u",
              F_DESTINATION: "s", F_SENDER: "s", F_SIGNATURE: "g"}
BUS_NAME, BUS_PATH, BUS_IFACE = "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus"
NAME_FLAG_DO_NOT_QUEUE = 0x4
MAX_MESSAGE = 128 * 1024 * 1024

_FIXED = {"y": ("B", 1), "b": ("I", 4), "n": ("h", 2), "q": ("H", 2), "i": ("i", 4), "u": ("I", 4),
          "x": ("q", 8), "t": ("Q", 8), "d": ("d", 8), "h": ("I", 4)}
_ALIGN = {"y": 1, "b": 4, "n": 2, "q": 2, "i": 4, "u": 4, "x": 8, "t": 8, "d": 8, "h": 4,
          "s": 4, "o": 4, "g": 1, "a": 4, "(": 8, "{": 8, "v": 1}


class DBusError(Exception):
    """Fehler, der als D-Bus-Fehlerantwort zurückgeht (name wie org.freedesktop.DBus.Error.Failed)."""

    def __init__(self, name: str, message: str = ""):
        super().__init__(message or name)
        self.name = name
        self.message = message


class Variant:
    """Wert mit ausdrücklicher Signatur, für v-Felder (a{sv} und Kopffelder)."""

    __slots__ = ("signature", "value")

    def __init__(self, signature: str, value: Any):
        self.signature = signature
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Variant) and (self.signature, self.value) == (other.signature, other.value)

    def __repr__(self) -> str:
        return f"Variant({self.signature!r}, {self.value!r})"


# ---- Signaturen --------------------------------------------------------------
def split_signature(sig: str) -> List[str]:
    """'sa{sv}(ii)' -> ['s', 'a{sv}', '(ii)']"""
    out, i = [], 0
    while i < len(sig):
        j = _complete_type_end(sig, i)
        out.append(sig[i:j])
        i = j
    return out


def _complete_type_end(sig: str, i: int) -> int:
    c = sig[i]
    if c == "a":
        return _complete_type_end(sig, i + 1)
    if c in "({":
        close = ")" if c == "(" else "}"
        depth, j = 0, i
        while j < len(sig):
            if sig[j] in "({":
                depth += 1
            elif sig[j] in ")}":
                depth -= 1
                if depth == 0:
                    if sig[j] != close:
                        break
                    return j + 1
            j += 1
        raise ValueError(f"unvollständige Signatur: {sig!r}")
    if c in _FIXED or c in "sogv":
        return i + 1
    raise ValueError(f"unbekannter Typ {c!r} in {sig!r}")


def guess_signature(value: Any) -> str:
    """Signatur für Werte in a{sv}: str, bool, int, float, Liste von str, Variant."""
    if isinstance(value, Variant):
        return value.signature
    if isinstance(value, bool):
        return "b"
    if isinstance(value, int):
        return "i"
    if isinstance(value, float):
        return "d"
    if isinstance(value, str):
        return "s"
    if isinstance(value, (list, tuple)) and all(isinstance(v, str) for v in value):
        return "as"
    raise TypeError(f"keine Signatur für {type(value).__name__}")


# ---- Schreiben -----------------------------------------------------------------
class _Writer:
    def __init__(self, offset: int = 0):
        self.buf = bytearray()
        self.offset = offset   # Ausrichtung zählt ab Nachrichtenanfang

    def pad(self, n: int) -> None:
        pos = self.offset + len(self.buf)
        self.buf.extend(b"\0" * ((-pos) % n))

    def write(self, sig: str, value: Any) -> None:
        c = sig[0]
        self.pad(_ALIGN[c])
        if c in _FIXED:
            fmt = _FIXED[c][0]
            if c == "b":
                value = 1 if value else 0
            self.buf.extend(struct.pack("<" + fmt, value))
        elif c in "so":
            raw = str(value).encode("utf-8")
            if b"\0" in raw:
                raise ValueError("Zeichenkette mit NUL-Byte")
            self.buf.extend(struct.pack("<I", len(raw)) + raw + b"\0")
        elif c == "g":
            raw = str(value).encode("ascii")
            self.buf.extend(struct.pack("<B", len(raw)) + raw + b"\0")
        elif c == "v":
            inner = value.signature if isinstance(value, Variant) else guess_signature(value)
            inner_value = value.value if isinstance(value, Variant) else value
            self.write("g", inner)
            self.write(inner, inner_value)
        elif c == "a":
            elem = sig[1:]
            len_pos = len(self.buf)
            self.buf.extend(b"\0\0\0\0")
            self.pad(_ALIGN[elem[0]])          # Auffüllung vor dem ersten Element zählt nicht mit
            start = len(self.buf)
            if elem[0] == "{":
                key_sig, val_sig = split_signature(elem[1:-1])
                for k, v in (value.items() if isinstance(value, dict) else value):
                    self.pad(8)
                    self.write(key_sig, k)
                    self.write(val_sig, v)
            else:
                for v in value:
                    self.write(elem, v)
            struct.pack_into("<I", self.buf, len_pos, len(self.buf) - start)
        elif c == "(":
            parts = split_signature(sig[1:-1])
            if len(parts) != len(value):
                raise ValueError(f"Struktur {sig} erwartet {len(parts)} Werte, bekam {len(value)}")
            for s, v in zip(parts, value):
                self.write(s, v)
        else:
            raise ValueError(f"Typ {c!r} nicht unterstützt")

    def write_all(self, signature: str, values: Tuple[Any, ...]) -> None:
        parts = split_signature(signature)
        if len(parts) != len(values):
            raise ValueError(f"Signatur {signature!r} erwartet {len(parts)} Werte, bekam {len(values)}")
        for s, v in zip(parts, values):
            self.write(s, v)


def marshal(signature: str, values: Tuple[Any, ...], offset: int = 0) -> bytes:
    w = _Writer(offset)
    w.write_all(signature, values)
    return bytes(w.buf)


# ---- Lesen -------------------------------------------------------------------------
class _Reader:
    def __init__(self, data: bytes, endian: str, offset: int = 0):
        self.data = data
        self.e = endian
        self.pos = offset

    def align(self, n: int) -> None:
        self.pos += (-self.pos) % n

    def read(self, sig: str) -> Any:
        c = sig[0]
        self.align(_ALIGN[c])
        if c in _FIXED:
            fmt, size = _FIXED[c]
            (v,) = struct.unpack_from(self.e + fmt, self.data, self.pos)
            self.pos += size
            return bool(v) if c == "b" else v
        if c in "so":
            (n,) = struct.unpack_from(self.e + "I", self.data, self.pos)
            self.pos += 4
            v = self.data[self.pos:self.pos + n].decode("utf-8")
            self.pos += n + 1
            return v
        if c == "g":
            n = self.data[self.pos]
            v = self.data[self.pos + 1:self.pos + 1 + n].decode("ascii")
            self.pos += n + 2
            return v
        if c == "v":
            inner = self.read("g")
            return Variant(inner, self.read(inner))
        if c == "a":
            (n,) = struct.unpack_from(self.e + "I", self.data, self.pos)
            self.pos += 4
            elem = sig[1:]
            self.align(_ALIGN[elem[0]])
            end = self.pos + n
            if elem[0] == "{":
                key_sig, val_sig = split_signature(elem[1:-1])
                out: Dict[Any, Any] = {}
                while self.pos < end:
                    self.align(8)
                    k = self.read(key_sig)
                    out[k] = self.read(val_sig)
                return out
            items = []
            while self.pos < end:
                items.append(self.read(elem))
            return items
        if c == "(":
            return tuple(self.read(s) for s in split_signature(sig[1:-1]))
        raise ValueError(f"Typ {c!r} nicht unterstützt")


def unmarshal(signature: str, data: bytes, endian: str = "<", offset: int = 0) -> List[Any]:
    r = _Reader(data, endian, offset)
    return [r.read(s) for s in split_signature(signature)]


# ---- Nachrichten ---------------------------------------------------------------
class Message:
    def __init__(self, mtype: int, serial: int, fields: Dict[int, Any], body: List[Any], flags: int = 0):
        self.type = mtype
        self.serial = serial
        self.fields = fields
        self.body = body
        self.flags = flags

    path = property(lambda self: self.fields.get(F_PATH, ""))
    interface = property(lambda self: self.fields.get(F_INTERFACE, ""))
    member = property(lambda self: self.fields.get(F_MEMBER, ""))
    sender = property(lambda self: self.fields.get(F_SENDER, ""))
    signature = property(lambda self: self.fields.get(F_SIGNATURE, ""))
    reply_serial = property(lambda self: self.fields.get(F_REPLY_SERIAL, 0))
    error_name = property(lambda self: self.fields.get(F_ERROR_NAME, ""))


def encode_message(mtype: int, serial: int, fields: Dict[int, Any], signature: str = "",
                   body: Tuple[Any, ...] = (), flags: int = 0) -> bytes:
    fields = dict(fields)
    if signature:
        fields[F_SIGNATURE] = signature
    body_bytes = marshal(signature, body) if signature else b""
    header_fields = [(code, Variant(FIELD_TYPE[code], value)) for code, value in sorted(fields.items())]
    head = marshal("yyyyuua(yv)", (ord("l"), mtype, flags, 1, len(body_bytes), serial, header_fields))
    head += b"\0" * ((-len(head)) % 8)
    return head + body_bytes


def decode_message(data: bytes) -> Tuple[Optional[Message], int]:
    """Eine Nachricht vom Anfang von data lesen; (None, 0), solange sie unvollständig ist."""
    if len(data) < 16:
        return None, 0
    endian = {ord("l"): "<", ord("B"): ">"}.get(data[0])
    if endian is None:
        raise ValueError("unbekannte Byte-Reihenfolge")
    body_len, serial, fields_len = struct.unpack_from(endian + "III", data, 4)
    header_len = 16 + fields_len
    header_len += (-header_len) % 8
    total = header_len + body_len
    if total > MAX_MESSAGE:
        raise ValueError("Nachricht zu groß")
    if len(data) < total:
        return None, 0
    raw_fields = unmarshal("a(yv)", data, endian, 12)[0]
    fields = {code: v.value for code, v in raw_fields}
    sig = fields.get(F_SIGNATURE, "")
    body = unmarshal(sig, data[:total], endian, header_len) if sig else []
    return Message(data[1], serial, fields, body, data[2]), total


# ---- Verbindung ------------------------------------------------------------------
def session_bus_address() -> str:
    addr = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not addr:
        runtime = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        if os.path.exists(os.path.join(runtime, "bus")):
            addr = "unix:path=" + os.path.join(runtime, "bus")
    return addr


def _unescape(value: str) -> str:
    out, i = bytearray(), 0
    raw = value.encode("utf-8")
    while i < len(raw):
        if raw[i:i + 1] == b"%" and i + 2 < len(raw) + 1:
            out.append(int(raw[i + 1:i + 3], 16))
            i += 3
        else:
            out.append(raw[i])
            i += 1
    return out.decode("utf-8")


def socket_path_from_address(address: str) -> str:
    """Erste unix-Adresse aus DBUS_SESSION_BUS_ADDRESS; abstrakte Namen mit führendem NUL."""
    for entry in address.split(";"):
        transport, _, params = entry.partition(":")
        if transport != "unix":
            continue
        kv = dict(p.split("=", 1) for p in params.split(",") if "=" in p)
        if "path" in kv:
            return _unescape(kv["path"])
        if "abstract" in kv:
            return "\0" + _unescape(kv["abstract"])
    raise OSError(f"keine unterstützte Bus-Adresse in {address!r}")


Handler = Callable[[Message], Tuple[str, Tuple[Any, ...]]]


class BusConnection:
    """Verbindung zum Sitzungsbus: blockierend angemeldet, danach Lesen auf Zuruf."""

    def __init__(self, address: Optional[str] = None, timeout: float = 5.0):
        address = address or session_bus_address()
        if not address:
            raise OSError("kein Sitzungsbus (DBUS_SESSION_BUS_ADDRESS leer)")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        self.sock.connect(socket_path_from_address(address))
        self._serial = 0
        self._buf = b""
        self._handlers: Dict[str, Handler] = {}
        self._signals: Dict[Tuple[Optional[str], str, str], Callable[[Message], None]] = {}
        self._auth()
        self.unique_name = self.call(BUS_NAME, BUS_PATH, BUS_IFACE, "Hello")[0]

    # -- Anmeldung
    def _auth(self) -> None:
        uid = str(os.getuid()).encode("ascii").hex()
        self.sock.sendall(b"\0AUTH EXTERNAL " + uid.encode("ascii") + b"\r\n")
        line = self._auth_line()
        if line.startswith(b"DATA"):
            self.sock.sendall(b"DATA\r\n")
            line = self._auth_line()
        if not line.startswith(b"OK"):
            raise OSError(f"D-Bus-Anmeldung abgelehnt: {line!r}")
        self.sock.sendall(b"BEGIN\r\n")

    def _auth_line(self) -> bytes:
        while b"\r\n" not in self._buf:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise OSError("Bus hat die Verbindung bei der Anmeldung geschlossen")
            self._buf += chunk
        line, _, self._buf = self._buf.partition(b"\r\n")
        return line

    # -- Senden
    def _next_serial(self) -> int:
        self._serial += 1
        return self._serial

    def send(self, data: bytes) -> None:
        self.sock.sendall(data)

    def call(self, destination: str, path: str, interface: str, member: str,
             signature: str = "", body: Tuple[Any, ...] = ()) -> List[Any]:
        """Blockierender Aufruf, nur für Hello und RequestName beim Start. Ankommende
        Aufrufe dazwischen werden normal beantwortet."""
        serial = self._next_serial()
        self.send(encode_message(METHOD_CALL, serial, {F_PATH: path, F_INTERFACE: interface, F_MEMBER: member,
                                                       F_DESTINATION: destination}, signature, body))
        while True:
            for msg in self._drain():
                if msg.type in (METHOD_RETURN, ERROR) and msg.reply_serial == serial:
                    if msg.type == ERROR:
                        raise DBusError(msg.error_name, str(msg.body[0]) if msg.body else "")
                    return msg.body
                self._dispatch(msg)
            chunk = self.sock.recv(65536)
            if not chunk:
                raise OSError("Bus hat die Verbindung geschlossen")
            self._buf += chunk

    def emit_signal(self, path: str, interface: str, member: str, signature: str = "",
                    body: Tuple[Any, ...] = (), destination: str = "") -> None:
        """Ein Signal senden (im Test spielt so ein nachgebautes kglobalacceld Drücken und Loslassen)."""
        fields = {F_PATH: path, F_INTERFACE: interface, F_MEMBER: member}
        if destination:
            fields[F_DESTINATION] = destination
        self.send(encode_message(SIGNAL, self._next_serial(), fields, signature, body, FLAG_NO_REPLY_EXPECTED))

    def request_name(self, name: str) -> bool:
        """True, wenn wir den Namen jetzt besitzen (1 primär, 4 schon unser)."""
        result = self.call(BUS_NAME, BUS_PATH, BUS_IFACE, "RequestName", "su", (name, NAME_FLAG_DO_NOT_QUEUE))[0]
        return result in (1, 4)

    def export(self, path: str, handler: Handler) -> None:
        self._handlers[path] = handler

    def add_match(self, rule: str) -> None:
        """Den Bus um Signale bitten, etwa "type='signal',interface='...',member='...'"."""
        self.call(BUS_NAME, BUS_PATH, BUS_IFACE, "AddMatch", "s", (rule,))

    def subscribe(self, path: Optional[str], interface: str, member: str,
                  callback: Callable[[Message], None]) -> None:
        """Rückruf für ein Signal; path None heißt: von jedem Objekt. add_match() muss
        der Aufrufer selbst ausführen, damit der Bus das Signal auch zustellt."""
        self._signals[(path, interface, member)] = callback

    # -- Lesen
    def fileno(self) -> int:
        return self.sock.fileno()

    def _drain(self) -> List[Message]:
        msgs = []
        while True:
            msg, used = decode_message(self._buf)
            if msg is None:
                return msgs
            self._buf = self._buf[used:]
            msgs.append(msg)

    def read_ready(self) -> bool:
        """Verfügbare Daten lesen und Aufrufe beantworten; False, wenn der Bus weg ist."""
        self.sock.setblocking(False)
        try:
            while True:
                try:
                    chunk = self.sock.recv(65536)
                except BlockingIOError:
                    break
                if not chunk:
                    return False
                self._buf += chunk
        finally:
            self.sock.setblocking(True)
        for msg in self._drain():
            self._dispatch(msg)
        return True

    def _dispatch(self, msg: Message) -> None:
        if msg.type == SIGNAL:
            callback = self._signals.get((msg.path, msg.interface, msg.member)) \
                or self._signals.get((None, msg.interface, msg.member))
            if callback is not None:
                try:
                    callback(msg)
                except Exception:  # ein Fehler im Rückruf darf die Verbindung nicht beenden
                    pass
            return
        if msg.type != METHOD_CALL:
            return  # verspätete Antworten interessieren nicht
        reply_wanted = not (msg.flags & FLAG_NO_REPLY_EXPECTED)
        handler = self._handlers.get(msg.path)
        try:
            if msg.interface == "org.freedesktop.DBus.Peer" and msg.member == "Ping":
                sig, body = "", ()
            elif handler is None:
                raise DBusError("org.freedesktop.DBus.Error.UnknownObject", f"kein Objekt unter {msg.path}")
            else:
                sig, body = handler(msg)
        except DBusError as exc:
            if reply_wanted:
                self._error(msg, exc.name, exc.message)
            return
        except Exception as exc:  # Fehler im Handler darf die Verbindung nicht beenden
            if reply_wanted:
                self._error(msg, "org.freedesktop.DBus.Error.Failed", f"{type(exc).__name__}: {exc}")
            return
        if reply_wanted:
            fields = {F_REPLY_SERIAL: msg.serial}
            if msg.sender:
                fields[F_DESTINATION] = msg.sender
            self.send(encode_message(METHOD_RETURN, self._next_serial(), fields, sig, body))

    def _error(self, msg: Message, name: str, text: str) -> None:
        fields = {F_REPLY_SERIAL: msg.serial, F_ERROR_NAME: name}
        if msg.sender:
            fields[F_DESTINATION] = msg.sender
        self.send(encode_message(ERROR, self._next_serial(), fields, "s", (text,)))

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass
