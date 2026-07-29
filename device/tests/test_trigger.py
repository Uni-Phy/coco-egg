"""One queue, every source. The keyboard, the console, and GPIO at M1.

The reason this exists rather than the loop reading stdin: a demo used to mean
pressing Enter in a terminal while watching a browser. The console can start a
turn now, and it does it by being a second CALLER of one route, not a second
route — so a turn from a browser and a turn from the terminal run the same code.
"""
import pytest

from coco_egg import trigger


@pytest.fixture(autouse=True)
def _drain():
    trigger.end()
    while trigger.wait(timeout=0) is not None:
        pass
    yield
    trigger.end()
    while trigger.wait(timeout=0) is not None:
        pass


def test_a_request_is_delivered_with_its_source():
    assert trigger.request("console")
    event = trigger.wait(timeout=1)
    assert event["source"] == "console"


def test_the_keyboard_carries_which_key():
    """The bench keys stay keyboard-only; the console has one action."""
    assert trigger.request("keyboard", key="w")
    assert trigger.wait(timeout=1) == {"source": "keyboard", "key": "w"}


def test_a_press_during_a_turn_is_rejected_not_queued():
    """An impatient child pressing space four times must not bank four turns."""
    trigger.begin()
    assert not trigger.request("console")
    assert not trigger.request("console")
    trigger.end()
    assert trigger.request("console")


def test_presses_banked_before_a_turn_started_do_not_survive_it():
    """A press during an answer meant "I'm impatient", not "ask another"."""
    assert trigger.request("console")      # queued, not yet consumed
    trigger.begin()
    trigger.end()
    assert trigger.wait(timeout=0) is None


def test_the_queue_is_one_deep():
    assert trigger.request("console")
    assert not trigger.request("keyboard", key="\r")
    assert trigger.wait(timeout=1)["source"] == "console"


def test_wait_times_out_rather_than_blocking_forever():
    """The loop polls so Ctrl-C stays responsive while nothing is happening."""
    assert trigger.wait(timeout=0.05) is None


def test_close_unblocks_the_loop():
    trigger.close()
    assert trigger.wait(timeout=1)["source"] == "eof"


def test_accepting_reports_whether_a_press_would_land():
    assert trigger.accepting()
    trigger.begin()
    assert not trigger.accepting()
    trigger.end()
    assert trigger.accepting()
