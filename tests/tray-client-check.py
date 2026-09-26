#!/usr/bin/python3
# =============================================================================
# hermes-os -- Client des Leisten-Symbols gegen ein nachgebautes Gateway prüfen
# =============================================================================
# Startet einen kleinen HTTP-Server auf 127.0.0.1 (freier Port), der genau die
# Endpunkte des Hermes-API-Servers nachstellt, die hermes_client.py benutzt:
# /health, /api/sessions, /api/sessions/{id}/messages, /v1/runs,
# /v1/runs/{id}/events (SSE mit Freigabe-Anfrage), /v1/runs/{id}/approval und
# /v1/runs/{id}/stop. Dann läuft ein ganzer Chat-Durchlauf durch den Client:
# Lebenszeichen, Gespräch anlegen, Verlauf, Nachricht senden, Ereignisse
# lesen, Freigabe beantworten, Abschluss mit Antworttext.
#
# Ohne Qt, ohne Netz nach draußen. Läuft mit jedem Python 3.9+:
#   tests/tray-client-check.py [--tray-dir DIR]
# Exit 0 = alles sauber. Das Validierungs-Gate (80-validate.sh, 7d) führt ihn
# im Image-Build aus.
# =============================================================================
import argparse
import json
import os
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

KEY = "test-key-0123456789abcdef"
HISTORY = [
    {"id": 1, "role": "user", "content": "Hallo", "timestamp": 1.0},
    {"id": 2, "role": "tool", "content": "os_status: ...", "timestamp": 2.0},
    {"id": 3, "role": "assistant", "content": "Hi! Was kann ich tun?", "timestamp": 3.0},
    {"id": 4, "role": "assistant", "content": [{"type": "text", "text": "kein String"}], "timestamp": 4.0},
    {"id": 5, "role": "user", "timestamp": 5.0,
     "content": [{"type": "text", "text": "Schau mal"},
                 {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}}]},
    {"id": 6, "role": "assistant", "content": "", "timestamp": 6.0},
]
IMAGE_URL = "data:image/png;base64,iVBORw0KGgo="


class FakeGateway(BaseHTTPRequestHandler):
    sessions = set()
    calls = []
    runs = []              # Rümpfe aller POST /v1/runs, in Reihenfolge
    approval_done = threading.Event()
    approval = {}
    lock = threading.Lock()

    def log_message(self, *args):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self):
        if self.headers.get("Authorization") == f"Bearer {KEY}":
            return True
        self._send(401, {"error": {"message": "Invalid gateway API key (API_SERVER_KEY)",
                                   "type": "gateway_auth_error", "code": "invalid_api_key"}})
        return False

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n).decode("utf-8") or "{}")

    def _frame(self, obj):
        self.wfile.write(("data: " + json.dumps(obj) + "\n\n").encode("utf-8"))
        self.wfile.flush()

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        with self.lock:
            self.calls.append(("GET", self.path))
        if path == "/health":
            self._send(200, {"status": "ok", "platform": "hermes-agent", "version": "Hermes Agent 0.21.5 (Nachbau)"})
            return
        if not self._authed():
            return
        parts = path.strip("/").split("/")
        if parts[:2] == ["api", "sessions"] and len(parts) == 4 and parts[3] == "messages":
            if parts[2] not in self.sessions:
                self._send(404, {"error": {"message": "Session not found", "code": "session_not_found"}})
                return
            self._send(200, {"object": "list", "data": HISTORY,
                             "pagination": {"limit": 40, "offset": 0, "returned": len(HISTORY)}})
            return
        if parts[:2] == ["v1", "runs"] and len(parts) == 4 and parts[3] == "events":
            run_id = parts[2]
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self._frame({"event": "message.delta", "run_id": run_id, "delta": "Ich "})
            self._frame({"event": "tool.started", "run_id": run_id, "tool": "terminal",
                         "preview": "sudo bootc upgrade --check"})
            self.wfile.write(b": keepalive\n\n")
            self.wfile.flush()
            self._frame({"event": "approval.request", "run_id": run_id, "request_id": "req-1",
                         "command": "sudo bootc upgrade --check",
                         "description": "Befehl berührt das laufende System",
                         "choices": ["once", "session", "deny"]})
            if not self.approval_done.wait(10):
                self._frame({"event": "run.failed", "run_id": run_id, "turn_exit_reason": "approval timeout"})
                self.wfile.write(b": stream closed\n\n")
                return
            self._frame({"event": "approval.responded", "run_id": run_id, "choice": self.approval.get("choice")})
            self._frame({"event": "tool.completed", "run_id": run_id, "tool": "terminal", "duration": 0.2,
                         "error": False})
            # data auf zwei Zeilen: SSE erlaubt das, der Parser muss es zusammensetzen
            self.wfile.write(b'data: {"event": "message.delta", "run_id": "' + run_id.encode() + b'",\n')
            self.wfile.write(b'data:  "delta": "pr\xc3\xbcfe."}\n\n')
            self.wfile.flush()
            self._frame({"event": "run.completed", "run_id": run_id, "completed": True,
                         "output": "Ich prüfe. Kein Update vorhanden."})
            self.wfile.write(b": stream closed\n\n")
            self.wfile.flush()
            return
        if parts[:2] == ["v1", "runs"] and len(parts) == 3:
            self._send(200, {"run_id": parts[2], "status": "completed"})
            return
        self._send(404, {"error": {"message": f"unbekannt: {path}", "code": "not_found"}})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        with self.lock:
            self.calls.append(("POST", path))
        if not self._authed():
            return
        body = self._body()
        parts = path.strip("/").split("/")
        if path == "/api/sessions":
            sid = str(body.get("id") or "")
            if sid in self.sessions:
                self._send(409, {"error": {"message": f"Session already exists: {sid}", "code": "session_exists"}})
                return
            self.sessions.add(sid)
            self._send(201, {"object": "hermes.session", "session": {"id": sid, "source": body.get("source")}})
            return
        if path == "/v1/runs":
            if not body.get("input") or body.get("session_id") not in self.sessions:
                self._send(400, {"error": {"message": "Missing 'input' field", "code": "invalid_request"}})
                return
            with self.lock:
                self.runs.append(body)
            self._send(202, {"run_id": f"run_{len(self.runs)}", "status": "started", "replayed": False})
            return
        if parts[:2] == ["v1", "runs"] and len(parts) == 4 and parts[3] == "approval":
            self.approval.update({"choice": body.get("choice"), "request_id": body.get("request_id")})
            self.approval_done.set()
            self._send(200, {"object": "hermes.run.approval_response", "run_id": parts[2],
                             "choice": body.get("choice")})
            return
        if parts[:2] == ["v1", "runs"] and len(parts) == 4 and parts[3] == "stop":
            self._send(200, {"run_id": parts[2], "status": "stopping"})
            return
        self._send(404, {"error": {"message": f"unbekannt: {path}", "code": "not_found"}})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tray-dir", default=os.environ.get("HERMES_OS_TRAY_DIR", "/usr/share/hermes-os/tray"))
    args = ap.parse_args()
    client_py = os.path.join(args.tray_dir, "hermes_client.py")
    if not os.path.isfile(client_py):
        print(f"FEHL  {client_py} fehlt")
        return 1
    sys.path.insert(0, args.tray_dir)
    import hermes_client as hc

    fail = 0

    def check(ok, label, detail=""):
        nonlocal fail
        if ok:
            print(f"OK    {label}")
        else:
            fail = 1
            print(f"FEHL  {label}" + (f": {detail}" if detail else ""))

    check(not hc.self_test(), "Selbsttest (SSE-Parser, .env-Leser)", str(hc.self_test()))

    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeGateway)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, name="fake-gateway", daemon=True).start()
    try:
        # Einstellungen wie das Symbol sie liest: aus HERMES_HOME/.env
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, ".env").write_text(f"OPENROUTER_API_KEY=sk-or-x\nAPI_SERVER_ENABLED=true\n"
                                         f"API_SERVER_KEY={KEY}\nAPI_SERVER_PORT={port}\n", encoding="utf-8")
            s = hc.gateway_settings(Path(tmp))
            check(s["port"] == port and s["key"] == KEY and s["key_usable"], "gateway_settings aus .env", str(s))
            short = Path(tmp, "short")
            short.mkdir()
            Path(short, ".env").write_text("API_SERVER_KEY=kurz\n", encoding="utf-8")
            check(not hc.gateway_settings(short)["key_usable"], "Schlüssel unter 16 Zeichen gilt als unbrauchbar")

        client = hc.GatewayClient("127.0.0.1", port, KEY)
        h = client.health()
        check(h.get("status") == "ok" and "version" in h, "GET /health", str(h))

        wrong = hc.GatewayClient("127.0.0.1", port, "falsch-falsch-falsch-1234")
        try:
            wrong.ensure_session("x")
            check(False, "falscher Schlüssel wird abgewiesen", "kein Fehler")
        except hc.GatewayError as exc:
            check(exc.status == 401 and "API_SERVER_KEY" in str(exc), "falscher Schlüssel wird abgewiesen (401)",
                  f"{exc.status} {exc}")

        dead = hc.GatewayClient("127.0.0.1", 1, KEY, timeout=2)
        try:
            dead.health(timeout=2)
            check(False, "Gateway aus wird erkannt", "kein Fehler")
        except hc.GatewayUnavailable:
            check(True, "Gateway aus wird als GatewayUnavailable gemeldet")

        check(client.ensure_session("hermes-os-tray") is True, "POST /api/sessions legt an (201)")
        check(client.ensure_session("hermes-os-tray") is False, "POST /api/sessions: vorhanden (409) ist kein Fehler")

        rows = client.history("hermes-os-tray")
        check([r["role"] for r in rows] == ["user", "assistant", "assistant", "user"]
              and rows[1]["content"].startswith("Hi!") and rows[1]["images"] == []
              and rows[2]["content"] == "kein String",
              "Verlauf: nur Nutzer und Assistent mit Inhalt, chronologisch, Teil-Listen als Text", str(rows))
        check(rows[3]["content"] == "Schau mal" and rows[3]["images"] == ["data:image/png;base64,AAAA"]
              and rows[3]["timestamp"] == 5.0,
              "Verlauf: Nachricht mit Bild liefert Text und Bild-URL getrennt", str(rows[3]))

        run_id = client.start_run("hermes-os-tray", "Gibt es ein Update?")
        check(run_id == "run_1", "POST /v1/runs liefert run_id", run_id)
        check(FakeGateway.runs[-1].get("input") == "Gibt es ein Update?",
              "POST /v1/runs ohne Bild: input bleibt ein String", str(FakeGateway.runs[-1]))

        names, deltas, approval, final = [], [], None, None
        for event in client.events(run_id):
            names.append(event.get("event"))
            if event.get("event") == "message.delta":
                deltas.append(event.get("delta"))
            elif event.get("event") == "approval.request":
                approval = event
                r = client.approve(run_id, "once", event.get("request_id", ""))
                check(r.get("choice") == "once", "POST /v1/runs/{id}/approval", str(r))
            elif event.get("event") == "run.completed":
                final = event
        check(names == ["message.delta", "tool.started", "approval.request", "approval.responded",
                        "tool.completed", "message.delta", "run.completed"],
              "Ereignisfolge des Runs", str(names))
        check("".join(deltas) == "Ich prüfe.", "Deltas, auch das über zwei data-Zeilen", repr("".join(deltas)))
        check(approval is not None and approval.get("choices") == ["once", "session", "deny"]
              and approval.get("command", "").startswith("sudo bootc"), "Freigabe-Anfrage mit Wahlmöglichkeiten",
              str(approval))
        check(final is not None and final.get("output", "").endswith("vorhanden."),
              "run.completed trägt den vollständigen Antworttext", str(final))
        check(FakeGateway.approval.get("request_id") == "req-1", "Freigabe nennt die request_id",
              str(FakeGateway.approval))
        r = client.stop(run_id)
        check(r.get("status") == "stopping", "POST /v1/runs/{id}/stop", str(r))
        auth_free = [c for c in FakeGateway.calls if c[1].startswith("/health")]
        check(len(auth_free) >= 1, "Health-Aufruf gesehen")

        # Bilder: input als Nachrichtenliste mit text- und image_url-Teilen
        run_id = client.start_run("hermes-os-tray", "Was ist das?", images=[IMAGE_URL])
        body = FakeGateway.runs[-1]
        wanted = [{"role": "user", "content": [{"type": "text", "text": "Was ist das?"},
                                               {"type": "image_url", "image_url": {"url": IMAGE_URL}}]}]
        check(run_id == "run_2" and body.get("input") == wanted and body.get("session_id") == "hermes-os-tray",
              "POST /v1/runs mit Bild: input als Nachrichtenliste mit text- und image_url-Teil", str(body)[:300])
        client.start_run("hermes-os-tray", "   ", images=[IMAGE_URL, IMAGE_URL])
        body = FakeGateway.runs[-1]
        check(body.get("input") == [{"role": "user", "content": [hc.image_part(IMAGE_URL), hc.image_part(IMAGE_URL)]}],
              "POST /v1/runs nur mit Bildern: kein leerer Text-Teil", str(body)[:300])
        cleaned, paths = hc.split_media_tags("Fertig, der Screenshot: MEDIA:/tmp/hermes/shot.png\n\nSonst nichts.")
        check(paths == ["/tmp/hermes/shot.png"] and cleaned == "Fertig, der Screenshot:\n\nSonst nichts.",
              "split_media_tags löst den Tag aus der Antwort und behält den Text", f"{cleaned!r} {paths}")
    finally:
        server.shutdown()
        server.server_close()

    print("ERGEBNIS: " + ("ok" if fail == 0 else "Fehler, siehe FEHL"))
    return fail


if __name__ == "__main__":
    sys.exit(main())
