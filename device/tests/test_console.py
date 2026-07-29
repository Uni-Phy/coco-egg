"""The console: serves the cue language, and stays out of the voice loop's way.

Most of what matters here is what the console must NOT do. It is an observer,
and a device teaching a class must not slow down, fail, or stop because
somebody opened a laptop — or because nobody did.
"""
import json
import threading
import urllib.request

import pytest

from coco_egg import console, events, presentation


@pytest.fixture
def server():
    """Console on an ephemeral port, so tests never collide with a real one."""
    cfg = {"console": {"enabled": True, "host": "127.0.0.1", "port": 0}}
    httpd = console.serve(cfg)
    assert httpd is not None
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(autouse=True)
def _no_leftover_subscribers():
    yield
    for fn in list(events._subscribers):
        events.unsubscribe(fn)


def get(url, timeout=5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return r.status, r.read()


def test_disabled_means_no_server():
    assert console.serve({"console": {"enabled": False}}) is None


def test_a_port_already_in_use_is_not_fatal(server):
    """A console that cannot bind must not stop a device from teaching."""
    port = int(server.rsplit(":", 1)[1])
    assert console.serve({"console": {"host": "127.0.0.1", "port": port}}) is None


def test_it_serves_the_page_and_the_cue_table(server):
    status, body = get(f"{server}/")
    assert status == 200 and b"<svg" in body

    status, body = get(f"{server}/cues")
    assert status == 200
    assert json.loads(body) == presentation.table()


def test_the_browser_gets_the_same_table_the_led_driver_will_read(server):
    """The student view is only a usable LED prototype while these agree.

    If the page ever carries its own colours or periods, the prototype and the
    M1 driver drift and the whole reason for the view goes away.
    """
    _, body = get(f"{server}/cues")
    served = json.loads(body)
    for name, spec in presentation.CUES.items():
        assert served[name]["colour"] == spec["colour"]
        assert served[name]["motion"] == spec["motion"]
        assert served[name]["min_dwell_ms"] == spec["min_dwell_ms"]


def test_nobody_connected_means_nobody_subscribed(server):
    """The property pack.py depends on.

    events.active() gates work that costs something to build — ranking and
    formatting every retrieval candidate. A console that subscribed at startup
    would make it permanently true, so a classroom device with no laptop open
    would pay for a trace nobody is reading.
    """
    get(f"{server}/health")
    assert not events.active()


def test_a_connected_browser_receives_events(server):
    received = []

    def read():
        req = urllib.request.Request(f"{server}/events")
        with urllib.request.urlopen(req, timeout=10) as r:
            for raw in r:
                line = raw.decode().strip()
                if line.startswith("data: "):
                    received.append(json.loads(line[6:]))
                    return

    reader = threading.Thread(target=read, daemon=True)
    reader.start()
    for _ in range(100):          # wait for the SSE handler to subscribe
        if events.active():
            break
        threading.Event().wait(0.02)
    assert events.active(), "the stream never subscribed"

    events.emit("state", state="THINKING")
    reader.join(timeout=5)
    assert received and received[0]["kind"] == "state"
    assert received[0]["state"] == "THINKING"


def test_a_disconnected_browser_unsubscribes(server):
    """Otherwise every closed tab leaves active() true forever."""
    def read():
        with urllib.request.urlopen(f"{server}/events", timeout=10) as r:
            r.read(1)             # headers are in; drop the connection

    t = threading.Thread(target=read, daemon=True)
    t.start()
    t.join(timeout=5)
    # The handler notices on its next write, so nudge it and let it unwind.
    for _ in range(100):
        events.emit("state", state="IDLE")
        if not events.active():
            break
        threading.Event().wait(0.02)
    assert not events.active()
