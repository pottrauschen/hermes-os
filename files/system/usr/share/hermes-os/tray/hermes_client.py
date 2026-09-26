"""hermes-os -- Client für den API-Server des Hermes-Gateways.

Nur Standardbibliothek: das Leisten-Symbol läuft mit Fedoras Python, nicht mit
der Hermes-Venv, und soll ohne Zusatzpakete auskommen. Der API-Server ist
Teil des Gateways (`hermes gateway run`) und lauscht auf 127.0.0.1:8642, sobald
in ~/.hermes/.env ein API_SERVER_KEY mit mindestens 16 Zeichen steht; das
First-Login-Skript legt ihn an. Alle Anfragen bleiben auf dem Rechner.

Benutzte Endpunkte (Hermes v2026.9.24):
  GET  /health                          ohne Schlüssel, Lebenszeichen
  POST /api/sessions                    Gespräch anlegen (201) oder vorhanden (409)
  GET  /api/sessions/{id}/messages      Verlauf, ?order=latest&limit=N chronologisch
  POST /v1/runs                         Nachricht senden, 202 mit run_id
  GET  /v1/runs/{id}/events             Ereignis-Strom (SSE): message.delta, tool.*,
                                        approval.request, run.completed|failed|cancelled
  POST /v1/runs/{id}/approval           Freigabe beantworten (once|session|always|deny)
  POST /v1/runs/{id}/stop               Run abbrechen

Der einfache Sessions-Strom (/api/sessions/{id}/chat/stream) liefert keine
Freigaben, deshalb läuft der Chat über Runs.
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8642
MIN_KEY_LENGTH = 16          # wie Hermes' has_usable_secret(min_length=16)
STREAM_IDLE_TIMEOUT = 60     # Hermes schickt alle 10 s ": keepalive"
APPROVAL_CHOICES = ("once", "session", "always", "deny")


class GatewayError(Exception):
    """HTTP-Fehler des API-Servers mit Status und Hermes-Fehlercode."""

    def __init__(self, message: str, status: int = 0, code: str = ""):
        super().__init__(message)
        self.status = status
        self.code = code


class GatewayUnavailable(GatewayError):
    """Kein Gateway erreichbar (Verbindung verweigert, Timeout)."""


# ---------------------------------------------------------------------------
# Einstellungen aus ~/.hermes
# ---------------------------------------------------------------------------

def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def read_env(path: Path) -> Dict[str, str]:
    """`.env` lesen: KEY=VALUE, optional `export `, Anführungszeichen, Kommentare."""
    values: Dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].rstrip()
        if key:
            values[key] = value
    return values


def _config_api_server(home: Path) -> Dict[str, Any]:
    """platforms.api_server aus config.yaml, falls PyYAML da ist; sonst leer."""
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    try:
        cfg = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    platforms = cfg.get("platforms") if isinstance(cfg, dict) else None
    entry = platforms.get("api_server") if isinstance(platforms, dict) else None
    if not isinstance(entry, dict):
        return {}
    extra = entry.get("extra") if isinstance(entry.get("extra"), dict) else {}
    out: Dict[str, Any] = {}
    for src in (entry, extra):
        for k in ("host", "port"):
            if src.get(k) not in (None, ""):
                out[k] = src[k]
    return out


def gateway_settings(home: Optional[Path] = None) -> Dict[str, Any]:
    """host, port und key so, wie das Gateway sie sieht: config.yaml vor .env vor Vorgabe."""
    home = Path(home) if home else hermes_home()
    env = read_env(home / ".env")
    cfg = _config_api_server(home)
    host = str(cfg.get("host") or env.get("API_SERVER_HOST") or DEFAULT_HOST)
    try:
        port = int(cfg.get("port") or env.get("API_SERVER_PORT") or DEFAULT_PORT)
    except (TypeError, ValueError):
        port = DEFAULT_PORT
    key = os.environ.get("API_SERVER_KEY") or env.get("API_SERVER_KEY", "")
    return {"host": host, "port": port, "key": key, "key_usable": len(key) >= MIN_KEY_LENGTH}


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------

def parse_sse(lines: Iterable[str]) -> Iterator[Dict[str, Any]]:
    """Server-Sent Events lesen: `data:`-Zeilen bis zur Leerzeile sammeln, JSON liefern.
    Kommentarzeilen (`: keepalive`, `: stream closed`) werden übersprungen; ein
    `event:`-Name landet als `_sse_event`, falls der Server einen schickt."""
    data: List[str] = []
    name = ""
    for raw in lines:
        line = raw.rstrip("\r\n")
        if line == "":
            if data:
                try:
                    payload = json.loads("\n".join(data))
                except ValueError:
                    payload = {"event": "unparsed", "raw": "\n".join(data)}
                if isinstance(payload, dict):
                    if name and "event" not in payload:
                        payload["event"] = name
                    if name:
                        payload["_sse_event"] = name
                    yield payload
            data, name = [], ""
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        if value.startswith(" "):
            value = value[1:]
        if field == "data":
            data.append(value)
        elif field == "event":
            name = value
    if data:
        try:
            payload = json.loads("\n".join(data))
        except ValueError:
            return
        if isinstance(payload, dict):
            yield payload


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class GatewayClient:
    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, key: str = "",
                 timeout: float = 15.0):
        self.host = host
        self.port = int(port)
        self.key = key
        self.timeout = timeout

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    # ---- Transport -----------------------------------------------------------
    def _headers(self, auth: bool = True) -> Dict[str, str]:
        h = {"Accept": "application/json", "User-Agent": "hermes-os-tray"}
        if auth:
            h["Authorization"] = f"Bearer {self.key}"
        return h

    def _open(self, method: str, path: str, body: Optional[Dict[str, Any]] = None,
              auth: bool = True, timeout: Optional[float] = None, accept: str = ""):
        data = None
        headers = self._headers(auth)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if accept:
            headers["Accept"] = accept
        req = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            return urllib.request.urlopen(req, timeout=timeout or self.timeout)
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", "replace") if exc.fp else ""
            message, code = raw[:400], ""
            try:
                parsed = json.loads(raw)
                err = parsed.get("error") if isinstance(parsed, dict) else None
                if isinstance(err, dict):
                    message = str(err.get("message") or message)
                    code = str(err.get("code") or err.get("type") or "")
                elif isinstance(err, str):
                    message = err
                elif isinstance(parsed, dict) and parsed.get("detail"):
                    message = str(parsed["detail"])
            except ValueError:
                pass
            raise GatewayError(message or f"HTTP {exc.code}", status=exc.code, code=code) from None
        except urllib.error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise GatewayUnavailable(f"Gateway nicht erreichbar: {reason}") from None
        except (socket.timeout, TimeoutError):
            raise GatewayUnavailable("Gateway antwortet nicht (Timeout)") from None
        except OSError as exc:
            raise GatewayUnavailable(f"Gateway nicht erreichbar: {exc}") from None

    def _json(self, method: str, path: str, body: Optional[Dict[str, Any]] = None,
              auth: bool = True, timeout: Optional[float] = None) -> Dict[str, Any]:
        with self._open(method, path, body, auth=auth, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except ValueError:
            raise GatewayError(f"Antwort kein JSON: {raw[:200]}", status=getattr(resp, "status", 0))
        return parsed if isinstance(parsed, dict) else {"data": parsed}

    # ---- Endpunkte -----------------------------------------------------------
    def health(self, timeout: float = 3.0) -> Dict[str, Any]:
        """Lebenszeichen ohne Schlüssel: {"status": "ok", "version": ...}."""
        return self._json("GET", "/health", auth=False, timeout=timeout)

    def ensure_session(self, session_id: str, source: str = "desktop") -> bool:
        """Gespräch anlegen; True wenn neu, False wenn es schon gab."""
        try:
            self._json("POST", "/api/sessions", {"id": session_id, "source": source})
            return True
        except GatewayError as exc:
            if exc.status == 409:
                return False
            raise

    def history(self, session_id: str, limit: int = 40) -> List[Dict[str, Any]]:
        """Die letzten Nachrichten des Gesprächs, chronologisch, nur Nutzer und Assistent."""
        data = self._json("GET", f"/api/sessions/{session_id}/messages?order=latest&limit={int(limit)}")
        out: List[Dict[str, Any]] = []
        for m in data.get("data") or []:
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "")
            content = m.get("content")
            if role not in ("user", "assistant") or not isinstance(content, str) or not content.strip():
                continue
            out.append({"role": role, "content": content, "timestamp": m.get("timestamp")})
        return out

    def start_run(self, session_id: str, text: str) -> str:
        """Nachricht als Run schicken; liefert die run_id (202)."""
        data = self._json("POST", "/v1/runs", {"input": text, "session_id": session_id})
        run_id = str(data.get("run_id") or "")
        if not run_id:
            raise GatewayError(f"Run ohne run_id angelegt: {data}")
        return run_id

    def events(self, run_id: str) -> Iterator[Dict[str, Any]]:
        """Ereignisse eines Runs als Generator, bis der Server den Strom schließt.
        Jeder Eintrag trägt `event` (z.B. message.delta) und `run_id`."""
        resp = self._open("GET", f"/v1/runs/{run_id}/events", timeout=STREAM_IDLE_TIMEOUT,
                          accept="text/event-stream")
        try:
            lines = (chunk.decode("utf-8", "replace") for chunk in iter(resp.readline, b""))
            for event in parse_sse(lines):
                yield event
        except (socket.timeout, TimeoutError):
            raise GatewayUnavailable("Ereignis-Strom abgerissen (Timeout)") from None
        except OSError as exc:
            raise GatewayUnavailable(f"Ereignis-Strom abgerissen: {exc}") from None
        finally:
            try:
                resp.close()
            except Exception:
                pass

    def approve(self, run_id: str, choice: str, request_id: str = "") -> Dict[str, Any]:
        if choice not in APPROVAL_CHOICES:
            raise ValueError(f"unbekannte Wahl: {choice}")
        body: Dict[str, Any] = {"choice": choice}
        if request_id:
            body["request_id"] = request_id
        return self._json("POST", f"/v1/runs/{run_id}/approval", body)

    def stop(self, run_id: str) -> Dict[str, Any]:
        return self._json("POST", f"/v1/runs/{run_id}/stop", {})

    def run_status(self, run_id: str) -> Dict[str, Any]:
        return self._json("GET", f"/v1/runs/{run_id}")


def self_test() -> List[str]:
    """Netzfreier Selbsttest für `hermes-os-tray --check`: liefert Fehler als Liste."""
    problems: List[str] = []
    sample = [": keepalive", "", "data: {\"event\": \"message.delta\", \"delta\": \"Ha\"}", "",
              "event: custom", "data: {\"a\": 1}", "", "data: {\"event\": \"run.completed\",",
              "data:  \"output\": \"Hallo\"}", "", ": stream closed", ""]
    got = list(parse_sse(sample))
    if [e.get("event") for e in got] != ["message.delta", "custom", "run.completed"]:
        problems.append(f"parse_sse: {got}")
    if got and got[-1].get("output") != "Hallo":
        problems.append("parse_sse: mehrzeiliges data nicht zusammengesetzt")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / ".env"
        p.write_text("# k\nexport API_SERVER_KEY='abcdefghijklmnop'\nAPI_SERVER_PORT=8643 # port\nX=\"y=z\"\n",
                     encoding="utf-8")
        env = read_env(p)
        if env.get("API_SERVER_KEY") != "abcdefghijklmnop" or env.get("API_SERVER_PORT") != "8643" \
           or env.get("X") != "y=z":
            problems.append(f"read_env: {env}")
        s = gateway_settings(Path(tmp))
        if s["port"] != 8643 or not s["key_usable"]:
            problems.append(f"gateway_settings: {s}")
    return problems


if __name__ == "__main__":
    errs = self_test()
    for e in errs:
        print("FEHL ", e)
    print("OK    hermes_client Selbsttest" if not errs else "ERGEBNIS: Fehler")
    raise SystemExit(1 if errs else 0)
