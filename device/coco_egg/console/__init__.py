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
import socket
import ssl
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import tls
from .. import events, presentation, trigger
from ..audio import clips

INDEX = pathlib.Path(__file__).parent / "index.html"

# Long enough not to be chatter, short enough that a proxy or a sleeping tab
# does not silently drop a connection that looks alive to the device.
KEEPALIVE_S = 15.0


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        """Silence. The access log would scroll the voice loop off the screen,
        and this shares a terminal with it."""

    def _send(self, code: int, body: bytes, ctype: str,
              no_store: bool = False) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if no_store:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:      # noqa: N802  (BaseHTTPRequestHandler's name)
        match self.path.split("?")[0]:
            case "/":
                # no-store because the page is edited between demos and a phone
                # holding yesterday's JavaScript against today's device looks
                # like a device fault, not a cache. It is one small file on a
                # LAN; there is nothing to save by caching it.
                self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8",
                           no_store=True)
            case "/cues":
                body = json.dumps(presentation.table()).encode()
                self._send(200, body, "application/json")
            case "/health":
                self._health()
            case "/events":
                self._stream()
            case path if path.startswith("/clip/"):
                self._clip(path[len("/clip/"):])
            case _:
                self._send(404, b"not found", "text/plain")

    def _health(self) -> None:
        """Alive, and whether the egg has a microphone of its own.

        The page needs the second part before anybody taps anything: on a
        device with no capture hardware the default action cannot work, and a
        phone holding a perfectly good microphone is the obvious fallback.
        Imported here rather than at module scope so a console can still be
        served on a machine where the audio stack will not import.
        """
        mic = False
        try:
            from ..audio.io import has_input
            mic = has_input()
        except Exception:      # noqa: BLE001 — health must answer, always
            pass
        self._send(200, json.dumps({"ok": True, "mic": mic}).encode(),
                   "application/json")

    def _clip(self, clip_id: str) -> None:
        """A spoken sentence, so a phone can be the speaker.

        404 on an unknown id is ordinary rather than exceptional: clips age out
        of a small ring buffer, and a browser that reconnected after a gap will
        ask for one that has already gone. The page skips and moves on.
        """
        wav = clips.path(clip_id.removesuffix(".wav"))
        if wav is None or not wav.is_file():
            self._send(404, b"expired", "text/plain")
            return
        try:
            body = wav.read_bytes()
        except OSError:
            self._send(404, b"unreadable", "text/plain")
            return
        self._send(200, body, "audio/wav")

    def do_POST(self) -> None:     # noqa: N802  (BaseHTTPRequestHandler's name)
        route = self.path.split("?")[0]
        if route == "/listen":
            self._listen()
            return
        if route != "/trigger":
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

    # A phone recording is a few seconds of 16 kHz mono; anything much larger is
    # not a question and should not be read into memory on a Pi.
    MAX_UPLOAD = 4 * 1024 * 1024

    def _listen(self) -> None:
        """A recording made on a phone, run as an ordinary turn.

        This is what lets the egg work with no microphone of its own. The audio
        goes onto the SAME trigger queue the button and the space bar use, so
        everything after it — ASR, retrieval, the tutor, TTS — is one pipeline
        rather than a browser-shaped copy of one.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if not 0 < length <= self.MAX_UPLOAD:
            self._send(413, b'{"ok":false,"reason":"size"}', "application/json")
            return
        audio = self.rfile.read(length)
        started = trigger.request("browser", audio=audio)
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
        except (BrokenPipeError, ConnectionResetError, ssl.SSLError):
            # The tab closed; the `with` has already unsubscribed. Over TLS the
            # same event arrives as SSLEOFError rather than a broken pipe, which
            # is why that is here: a closed tab is not an error to report.
            pass


class _Redirect(BaseHTTPRequestHandler):
    """Answers a plain-HTTP request on the TLS port with "go to https".

    Without this the port is TLS-only, and a phone given `egg.local:8090` with
    no scheme tries http:// first, gets its connection dropped mid-request, and
    reports "cannot open the page" — the same message it shows for a device
    that is not there at all. Somebody debugging that looks at the network, the
    hotspot and the mDNS name before they think to type eight more characters.

    302 rather than 301: a permanent redirect is cached hard by browsers, and
    would keep forcing https on a device whose console was later run without a
    certificate — a confusing failure to inherit from a demo.
    """

    protocol_version = "HTTP/1.1"
    server_version = "coco-egg"

    def log_message(self, fmt, *args):
        """Silence, for the reason Handler is silent: shared terminal."""

    def _go(self) -> None:
        # Host carries the port the user actually typed, which is what the
        # redirect has to preserve; falling back to the socket's own address
        # covers an HTTP/1.0 client with no Host header.
        host = self.headers.get("Host") or "%s:%d" % self.server.server_address
        self.send_response(302)
        self.send_header("Location", f"https://{host}{self.path}")
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST = do_HEAD = _go      # noqa: N815  (stdlib's naming)


# A browser opens speculative connections it never writes to, so this is a
# thread parking rather than the accept loop stalling — but it still has to end.
SNIFF_TIMEOUT_S = 10.0


class _Server(ThreadingHTTPServer):
    """Serves HTTPS and an http->https redirect on one port.

    Sniffing beats a second listener because the port is the part people are
    given, and they cannot be told a different one for the mistake they are
    about to make. A TLS ClientHello begins with 0x16 (handshake); every HTTP
    request begins with an ASCII method. One peeked byte separates them.

    Also silences the traceback socketserver prints when a client TCP-hangs up
    before or during a request: browsers open speculative connections and tabs
    close mid-SSE, and neither is actionable.
    """

    ssl_ctx: ssl.SSLContext | None = None

    def finish_request(self, request, client_address) -> None:
        # Runs on the worker thread (ThreadingMixIn), so a peek that waits
        # cannot hold up anybody else's connection.
        if self.ssl_ctx is not None:
            try:
                request.settimeout(SNIFF_TIMEOUT_S)
                first = request.recv(1, socket.MSG_PEEK)
                request.settimeout(None)     # SSE needs a blocking socket back
            except OSError:
                return                        # hung up, or never spoke
            if first != b"\x16":
                if first:
                    _Redirect(request, client_address, self)
                return
            try:
                request = self.ssl_ctx.wrap_socket(request, server_side=True)
            except (ssl.SSLError, OSError):
                return                        # a failed handshake is not news
        super().finish_request(request, client_address)

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        # ssl.SSLError included because a tab closing mid-stream over TLS raises
        # SSLEOFError, not a broken pipe. A bad certificate fails earlier, at
        # load_cert_chain, so nothing diagnostic is being swallowed here.
        if isinstance(exc, (ConnectionResetError, BrokenPipeError,
                            ConnectionAbortedError, ssl.SSLError)):
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

    # HTTPS is not decoration here: a browser refuses getUserMedia outside a
    # secure context, so without it a phone cannot be the microphone at all.
    # Falling back to plain HTTP keeps the page and the speaker working.
    scheme = "http"
    if c.get("tls", True):
        pair = tls.ensure(c.get("cert_dir", "state"),
                          tls.local_addresses(c.get("cert_hosts")))
        if pair:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(*pair)
            # Per-connection, not on the listening socket: the server sniffs
            # each connection so plain http on this port gets a redirect
            # instead of a dropped connection (_Server).
            httpd.ssl_ctx = ctx
            scheme = "https"
        else:
            print("  console: no certificate — phone microphone will not work",
                  flush=True)

    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"  console: {scheme}://{host}:{port}  "
          f"(no auth yet — LAN only, live events only)", flush=True)
    if scheme == "https":
        print("  console: self-signed — accept the warning once per phone",
              flush=True)
    return httpd
