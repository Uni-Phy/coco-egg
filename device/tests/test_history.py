"""Conversation memory, and the prompt ordering that makes it affordable."""
import pytest

from coco_egg import config
from coco_egg.tutor import llama_client
from coco_egg.tutor.history import History


@pytest.fixture
def cfg():
    c = config.load(path=None)
    c["tutor"]["embed_url"] = None      # lexical path; no server needed
    c["tutor"]["pack"] = None
    return c


@pytest.fixture(autouse=True)
def _clean():
    llama_client.forget()
    yield
    llama_client.forget()


def test_window_keeps_only_the_last_n_turns():
    h = History(turns=2)
    for i in range(5):
        h.add(f"q{i}", f"a{i}")
    assert len(h) == 2
    assert [m["content"] for m in h.messages()] == ["q3", "a3", "q4", "a4"]


def test_empty_turns_are_not_recorded():
    """A turn with nothing heard or nothing said is not a memory."""
    h = History()
    h.add("", "an answer")
    h.add("a question", "   ")
    assert len(h) == 0


def test_long_replies_are_truncated():
    """The model rambles past its 3-sentence instruction; the window must not."""
    h = History()
    h.add("q", "x" * 5000)
    assert len(h.messages()[1]["content"]) <= 320


def test_history_sits_above_the_volatile_tail(cfg):
    """Ordering is the design: static, then history, then grounding+question.

    History is append-only, so above the volatile tail it lands in
    llama-server's cached prefix. Below it, every retained turn would be
    re-prefilled on every later turn — measured at ~26 tokens each, forever.
    """
    llama_client.remember("what is friction", "It resists sliding.", cfg)
    llama_client.remember("why do we need it", "It lets you walk.", cfg)
    messages, _ = llama_client.build_messages("how do brakes work", cfg)

    assert [m["role"] for m in messages] == [
        "system", "user", "assistant", "user", "assistant", "user"]
    # The new question is last; the prior turns precede it unchanged.
    assert messages[-1]["content"].endswith("how do brakes work")
    assert messages[1]["content"] == "what is friction"


def test_appending_a_turn_does_not_disturb_the_existing_prefix(cfg):
    """The cache-safety property, stated as a test.

    Adding a turn must only APPEND messages. If an earlier message changed,
    the shared prefix would break and the whole conversation would be
    re-prefilled — which is exactly the cost this design exists to avoid.
    """
    llama_client.remember("q1", "a1", cfg)
    before, _ = llama_client.build_messages("current", cfg)
    llama_client.remember("q2", "a2", cfg)
    after, _ = llama_client.build_messages("current", cfg)

    # every message of `before` except the volatile last one is a prefix of `after`
    assert after[:len(before) - 1] == before[:-1]
    assert len(after) == len(before) + 2


def test_history_can_be_disabled(cfg):
    cfg["tutor"]["history_turns"] = 0
    llama_client.remember("q", "a", cfg)
    messages, _ = llama_client.build_messages("only question", cfg)
    assert [m["role"] for m in messages] == ["system", "user"]


def test_forget_clears_between_learners(cfg):
    llama_client.remember("q", "a", cfg)
    llama_client.forget()
    messages, _ = llama_client.build_messages("fresh", cfg)
    assert [m["role"] for m in messages] == ["system", "user"]
