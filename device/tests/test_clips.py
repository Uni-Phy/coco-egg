"""Serving spoken audio to a browser, so an egg needs no speaker.

Two things matter here. The clip has to be fetchable while the browser still
wants it, and the files must not accumulate — tts.synthesize() opens its WAV
with delete=False and nothing removed them, so a device left running grew one
temp file per sentence spoken, forever.
"""
import pathlib
import urllib.error
import urllib.request
import wave

import pytest

from coco_egg import console, events
from coco_egg.audio import clips


@pytest.fixture
def server():
    cfg = {"console": {"enabled": True, "host": "127.0.0.1", "port": 0}}
    httpd = console.serve(cfg)
    assert httpd is not None
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(autouse=True)
def _clean():
    clips.clear()
    yield
    clips.clear()
    for fn in list(events._subscribers):
        events.unsubscribe(fn)


def a_wav(tmp_path, name="clip.wav"):
    path = tmp_path / name
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x01" * 800)
    return path


def test_a_published_clip_can_be_fetched_and_is_a_wav(server, tmp_path):
    clip = clips.publish(str(a_wav(tmp_path)))
    with urllib.request.urlopen(f"{server}/clip/{clip}.wav", timeout=5) as r:
        assert r.status == 200
        assert r.headers["Content-Type"] == "audio/wav"
        assert r.read()[:4] == b"RIFF"


def test_the_id_works_with_or_without_the_extension(server, tmp_path):
    clip = clips.publish(str(a_wav(tmp_path)))
    for suffix in ("", ".wav"):
        with urllib.request.urlopen(f"{server}/clip/{clip}{suffix}", timeout=5) as r:
            assert r.status == 200


def test_an_expired_clip_is_a_404_rather_than_a_crash(server):
    """Ordinary, not exceptional: a browser reconnecting after a gap asks for
    clips that have already aged out, and the page skips them."""
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"{server}/clip/deadbeef.wav", timeout=5)
    assert exc.value.code == 404


def test_old_clips_are_evicted_and_their_files_deleted(tmp_path):
    """The leak this fixes: one temp WAV per sentence, kept forever."""
    made = [a_wav(tmp_path, f"c{i}.wav") for i in range(clips.MAX_CLIPS + 6)]
    ids = [clips.publish(str(p)) for p in made]

    assert clips.count() == clips.MAX_CLIPS
    # The oldest six are gone from the registry AND off the disk.
    for path, clip in zip(made[:6], ids[:6]):
        assert clips.path(clip) is None
        assert not path.exists()
    # The newest survive both.
    for path, clip in zip(made[-3:], ids[-3:]):
        assert clips.path(clip) is not None
        assert path.exists()


def test_ids_are_random_not_a_counter(tmp_path):
    """The console has no auth, so ids should not be walkable. A counter would
    let anyone enumerate every sentence the device has spoken."""
    ids = [clips.publish(str(a_wav(tmp_path, f"n{i}.wav"))) for i in range(8)]
    assert len(set(ids)) == 8
    assert all(len(i) == 8 and all(c in "0123456789abcdef" for c in i) for i in ids)
    assert not all(b.isdigit() and a.isdigit() and int(b) == int(a) + 1
                   for a, b in zip(ids, ids[1:]))


def test_clear_removes_the_files(tmp_path):
    paths = [a_wav(tmp_path, f"x{i}.wav") for i in range(3)]
    for p in paths:
        clips.publish(str(p))
    clips.clear()
    assert clips.count() == 0
    assert not any(p.exists() for p in paths)


# --- how the device decides where audio comes out --------------------------

@pytest.mark.parametrize("where, publishes, plays", [
    ("device", False, True),     # unchanged default: aplay only
    ("browser", True, False),    # no speaker on the egg at all
    ("both", True, True),
])
def test_audio_output_routes_correctly(monkeypatch, tmp_path, where, publishes, plays):
    from coco_egg import main

    played, emitted = [], []
    monkeypatch.setattr(main, "play_wav", lambda p, c: played.append(p))
    monkeypatch.setattr(main.events, "emit",
                        lambda kind, **f: emitted.append((kind, f)))

    wav = str(a_wav(tmp_path, f"{where}.wav"))
    main.speak(wav, 0, "hello", {"audio": {"output": where}})

    kind, fields = emitted[-1]
    assert kind == "spoken"
    assert (fields["clip"] is not None) is publishes
    assert bool(played) is plays


def test_the_clip_id_on_the_wire_actually_resolves(server, monkeypatch, tmp_path):
    """End to end: what the event carries is what the browser can fetch."""
    from coco_egg import main

    monkeypatch.setattr(main, "play_wav", lambda p, c: None)
    seen = []
    monkeypatch.setattr(main.events, "emit", lambda kind, **f: seen.append(f))
    main.speak(str(a_wav(tmp_path, "wire.wav")), 0, "hi", {"audio": {"output": "browser"}})

    clip = seen[-1]["clip"]
    with urllib.request.urlopen(f"{server}/clip/{clip}.wav", timeout=5) as r:
        assert r.read()[:4] == b"RIFF"


def test_the_page_offers_the_listen_control():
    """A tap is required by every browser's autoplay policy, so the control has
    to exist rather than the page trying to play unprompted."""
    page = (pathlib.Path(console.__file__).parent / "index.html").read_text()
    assert 'id="listen"' in page
    assert "/clip/" in page
    # A queue, not one Audio per sentence: overlapping playback would make a
    # multi-sentence answer unintelligible.
    assert "playNext" in page
