"""The console: a student view that prototypes the LED ring, and a dev trace.

Two audiences, one page, because they want the same events. The learner needs
to know it heard them (spec §5 calls the ring "non-negotiable UX"); the operator
needs to see what it retrieved and where the seconds went. `d` toggles between
them.

The student half is a renderer of `presentation.CUES` and nothing else — same
colours, periods and dwells the M1 LED driver will read, served to the browser
as JSON at /cues rather than copied into the page. The moment those diverge it
stops being a usable LED prototype, which is most of why it exists.

Stdlib only: ThreadingHTTPServer plus Server-Sent Events. A WebSocket would
mean a dependency and a handshake for a stream that only ever goes one way.

Three properties inherited from events.py, and worth restating because this is
the module that could break them:

- **It subscribes only while a browser is connected.** A permanent subscriber
  would make events.active() always true, and pack.py ranks and formats every
  retrieval candidate when it is — work done for nobody on a device with no
  laptop open, which is the normal case.
- **It cannot slow a turn.** events.Stream is a bounded queue that sheds its
  oldest event rather than making the egg wait for a browser on a slow LAN.
- **It cannot fail a turn.** A subscriber that raises is dropped by the bus.

SECURITY: there is no authentication yet, and the events carry what a child
said out loud. It is bound to the LAN for a demo, deliberately serves only LIVE
events (never stored transcripts), and says so on the page. Auth lands before
this is exposed anywhere it is not being watched.
"""
from __future__ import annotations

import json
import pathlib
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import events, presentation, trigger

INDEX = pathlib.Path(__file__).parent / "index.html"

# Long enough not to be chatter, short enough that a proxy or a sleeping tab
# does not silently drop a connection that looks alive to the device.
KEEPALIVE_S = 15.0


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        """Silence. The access log would scroll the voice loop off the screen,
        and this shares a terminal with it."""

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:      # noqa: N802  (BaseHTTPRequestHandler's name)
        match self.path.split("?")[0]:
            case "/":
                self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            case "/cues":
                body = json.dumps(presentation.table()).encode()
                self._send(200, body, "application/json")
            case "/health":
                self._send(200, b'{"ok":true}', "application/json")
            case "/events":
                self._stream()
            case _:
                self._send(404, b"not found", "text/plain")

    def do_POST(self) -> None:     # noqa: N802  (BaseHTTPRequestHandler's name)
        if self.path.split("?")[0] != "/trigger":
            self._send(404, b"not found", "text/plain")
            return
        # The console is the demo surface, so space bar here has to do what
        # Enter does in the terminal. Rejected rather than queued while a turn
        # runs, so the page can say "still answering" instead of silently
        # banking presses (trigger.py).
        started = trigger.request("console")
        body = json.dumps({"ok": started,
                           "reason": "" if started else "busy"}).encode()
        self._send(200 if started else 409, body, "application/json")

    def _stream(self) -> None:
        """SSE. Subscribes on connect and unsubscribes on disconnect."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            with events.Stream() as stream:
                while True:
                    event = stream.get(timeout=KEEPALIVE_S)
                    if event is None:
                        # A comment frame: keeps the socket warm and is how a
                        # vanished client is noticed, since nothing else writes.
                        self.wfile.write(b": keepalive\n\n")
                    else:
                        if stream.dropped:
                            event = {**event, "dropped": stream.dropped}
                        self.wfile.write(f"data: {json.dumps(event)}\n\n".encode())
                    self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass       # the tab closed; the `with` has already unsubscribed


class _Server(ThreadingHTTPServer):
    """Silences the traceback socketserver prints when a client TCP-hangs up
    before or during the request. Browsers open speculative connections and
    tabs close mid-SSE; neither is actionable."""

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError,
                            ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def serve(cfg: dict) -> ThreadingHTTPServer | None:
    """Start the console on a daemon thread. Never fatal to the voice loop.

    A port already in use, or a missing page, must not stop a device teaching —
    the console is an observer, and the egg's job does not depend on being
    observed.
    """
    c = cfg.get("console", {})
    if not c.get("enabled", True):
        return None
    host, port = c.get("host", "0.0.0.0"), int(c.get("port", 8090))
    try:
        httpd = _Server((host, port), Handler)
    except OSError as e:
        print(f"  console: not started ({e.__class__.__name__}: {e})", flush=True)
        return None
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"  console: http://{host}:{port}  "
          f"(no auth yet — LAN only, live events only)", flush=True)
    return httpd
