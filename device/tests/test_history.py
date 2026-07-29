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


def test_the_window_never_grows_past_its_cap():
    h = History(turns=4)
    for i in range(20):
        h.add(f"q{i}", f"a{i}")
        assert len(h) <= 4
    assert len(h) >= 1     # a trim must never empty it


def test_the_newest_turn_is_always_kept():
    h = History(turns=4)
    for i in range(20):
        h.add(f"q{i}", f"a{i}")
        assert h.last_question() == f"q{i}"


def test_eviction_is_batched_not_sliding():
    """The measured reason this is not a deque (see the module docstring).

    A sliding window shifts the prompt prefix on every turn once it is full, so
    llama-server re-prefills the whole conversation every time: measured at 74
    tokens when appending versus 203 when one turn was evicted. Batching means
    most turns are pure appends onto a prefix that is still cached.
    """
    h = History(turns=4)
    trims, appends = 0, 0
    for i in range(20):
        before = [m["content"] for m in h.messages()]
        h.add(f"q{i}", f"a{i}")
        after = [m["content"] for m in h.messages()]
        if after[:len(before)] == before:
            appends += 1        # prefix preserved: cache survives
        else:
            trims += 1
    assert trims, "nothing was ever evicted — the cap is not being applied"
    # A deque would trim on every turn once full. Batching must do far better.
    assert appends > trims * 2, f"{appends} appends vs {trims} trims"


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
    # A real follow-up, not a bare noun: a one-word turn is a topic nomination
    # and deliberately drops the history, which would test the opposite thing.
    llama_client.remember("q1", "a1", cfg)
    before, _ = llama_client.build_messages("how does that work", cfg)
    llama_client.remember("q2", "a2", cfg)
    after, _ = llama_client.build_messages("how does that work", cfg)

    # every message of `before` except the volatile last one is a prefix of `after`
    assert after[:len(before) - 1] == before[:-1]
    assert len(after) == len(before) + 2


def test_history_can_be_disabled(cfg):
    cfg["tutor"]["history_turns"] = 0
    llama_client.remember("q", "a", cfg)
    messages, _ = llama_client.build_messages("only question", cfg)
    assert [m["role"] for m in messages] == ["system", "user"]


def test_forget_clears_between_learners(cfg):
    # Asked as a question, so the empty history is what forget() did and not a
    # side effect of the topic-nomination rule.
    llama_client.remember("q", "a", cfg)
    llama_client.forget()
    messages, _ = llama_client.build_messages("how does a pump work", cfg)
    assert [m["role"] for m in messages] == ["system", "user"]


def test_followup_borrows_the_previous_subject(cfg):
    """"why do we need it" has no topic; on the device it retrieved ENERGY
    after a friction question, because the words carry nothing."""
    llama_client.remember("what is friction", "It resists sliding.", cfg)
    assert llama_client.retrieval_query("why do we need it").startswith("what is friction")


def test_a_real_topic_change_is_not_dragged_back(cfg):
    """A standalone question must not be blended with the previous subject."""
    llama_client.remember("what is friction", "It resists sliding.", cfg)
    assert llama_client.retrieval_query("what is a fraction") == "what is a fraction"


def test_no_history_means_no_rewrite():
    assert llama_client.retrieval_query("why do we need it") == "why do we need it"


def test_only_the_top_chunk_is_quoted_in_full(cfg):
    """Runners-up are named, not quoted — that is the latency lever."""
    hits = [{"title": "Friction", "text": "A" * 400},
            {"title": "Gravity", "text": "B" * 400},
            {"title": "Levers", "text": "C" * 400}]
    material = llama_client._material(hits, cfg)
    assert "A" * 400 in material
    assert "B" * 400 not in material
    assert "Gravity" in material and "Levers" in material   # still named


@pytest.mark.parametrize("question, rewritten", [
    ("why do we need it", True),        # bare pronoun
    ("tell me more", True),             # nothing to search on at all
    ("what is a fraction", False),      # one content word, but standalone
    ("what is gravity", False),         # the commonest tutor question shape
    ("how does a lever work", False),
])
def test_only_context_dependent_questions_are_rewritten(cfg, question, rewritten):
    llama_client.remember("what is friction", "It resists sliding.", cfg)
    q = llama_client.retrieval_query(question)
    assert (q != question) is rewritten
