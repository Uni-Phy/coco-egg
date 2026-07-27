import pathlib

import pytest

from coco_egg import config
from coco_egg.tutor import llama_client, prompts
from coco_egg.tutor.pack import Pack, _content_tokens, _is_topic_match, _tokens

PACKS_DIR = pathlib.Path(__file__).parents[2] / "fixtures" / "packs"
PACK_PATH = PACKS_DIR / "science-maths.json"


@pytest.fixture
def pack():
    return Pack.load(PACK_PATH)


@pytest.fixture
def library():
    return Pack.load_config(str(PACKS_DIR))


def test_retrieve_ranks_relevant_chunk_first(pack):
    hits = pack.retrieve("how do plants make their food")
    assert hits and hits[0]["id"] in ("photosynthesis", "plants-soil")


def test_retrieve_off_topic_returns_nothing(pack):
    assert pack.retrieve("zzz qqq xyzzy") == []


@pytest.mark.parametrize("question", [
    "What is the range?",       # used to score on "what"/"is"/"the" alone
    "What is game theory?",
    "who was Ashoka",
    "what is 7 times 8",
])
def test_retrieve_leaves_general_questions_to_the_model(pack, question):
    """v0.2: no hit is the normal outcome — the model answers these itself.

    Grounding an unrelated lesson is worse than grounding nothing here: it
    drags the answer away from what the student actually asked.
    """
    assert pack.retrieve(question) == []


def test_retrieve_handles_soil_misconception(pack):
    hits = pack.retrieve("why does the plant not just eat the soil")
    assert hits[0]["id"] == "plants-soil"


def test_library_merges_subjects_into_one_corpus(library):
    assert len(library.subjects) >= 2
    assert len(library.chunks) > len(Pack.load(PACK_PATH).chunks)
    assert all(c.get("subject") for c in library.chunks)


@pytest.mark.parametrize("question, subject_word", [
    ("Who was Ashoka?", "Civics"),
    ("What is a Gram Panchayat?", "Civics"),
    ("What is photosynthesis?", "Science"),
    ("What are fractions?", "Maths"),   # dedicated course beats the old sampler
])
def test_retrieval_routes_across_subjects(library, question, subject_word):
    """A question lands in the right subject once several packs are loaded.

    Ashoka is the case that matters: ungrounded, the small model placed him in
    the Gupta Empire (docs/model-notes.md §3). Adding the subject is what
    fixes that, which is the whole thin-model-plus-packs bet.
    """
    hits = library.retrieve(question)
    assert hits, f"{question!r} retrieved nothing"
    assert subject_word in hits[0]["subject"]


@pytest.mark.parametrize("question", [
    "What did I have for breakfast?",   # fractions lesson says "you have"
    "where did I leave my slippers",    # nothing in the library answers this
])
def test_one_incidental_word_is_not_a_topic_match(library, question):
    """Sharing a single body word is not evidence a lesson is relevant.

    Both of these grounded wrongly once, and the 0.6B then built its whole
    answer from the bad chunk — claiming it ate a roti, and explaining a blue
    sky with evaporation. Asserts the outcome rather than the mechanism: two
    layers now stop them: "have" is a stopword, and neither question shares a
    topic term with any lesson. ("Why is the sky blue" used to live here; the
    sky course now teaches it, so it is a hit rather than a false positive.)
    """
    assert library.retrieve(question) == []


@pytest.mark.parametrize("question, chunk_title", [
    ("what is my father's job", "A bird's nest"),      # both split to a bare "s"
    ("where do we keep the goat's feed", "A bird's nest"),
])
def test_possessive_debris_is_not_a_match(question, chunk_title):
    """`\\w+` splits "bird's" into "bird" + "s", and "s" in a title scored 3x.

    That made ANY question with a possessive topic-match ANY chunk whose title
    had one. Found while drafting course material, where titles like "A bird's
    nest" are natural to write.
    """
    chunk = {"_title_tokens": set(_tokens(chunk_title)),
             "_tokens": set(_tokens(chunk_title + " is built high in a tree"))}
    shared = [t for t in _content_tokens(question) if t in chunk["_tokens"]]
    assert "s" not in shared
    assert not _is_topic_match(shared, chunk)


def test_missing_pack_path_is_skipped_not_fatal(tmp_path):
    """One un-synced pack must not stop the egg teaching the others."""
    lib = Pack.load_config([str(PACK_PATH), str(tmp_path / "not-there.json")])
    assert lib and lib.chunks


def test_fallback_speaks_canned_explanation(pack, monkeypatch):
    """LLM unreachable -> the pack's pre-written explanation, sentence-split."""
    cfg = config.load(path=None)
    cfg["tutor"]["llama_url"] = "http://127.0.0.1:9"  # closed port
    cfg["tutor"]["pack"] = str(PACK_PATH)
    monkeypatch.setattr(llama_client, "_pack", None)
    sentences = list(llama_client.stream_sentences("what is photosynthesis", cfg))
    assert len(sentences) >= 2
    assert "photosynthesis" in " ".join(sentences).lower()


def test_fallback_unknown_when_no_match(pack, monkeypatch):
    """No LLM and no matching lesson: say so, don't invent.

    Asserts against the UNKNOWN constant rather than its wording — the text is
    product copy and gets reworded; the behaviour is the contract.
    """
    cfg = config.load(path=None)
    cfg["tutor"]["llama_url"] = "http://127.0.0.1:9"
    cfg["tutor"]["pack"] = str(PACK_PATH)
    monkeypatch.setattr(llama_client, "_pack", None)
    sentences = list(llama_client.stream_sentences("qqq zzz xyzzy", cfg))
    assert " ".join(sentences) == prompts.UNKNOWN


def test_emoji_are_stripped_before_speaking():
    """The reply is spoken, so a smiley is either read aloud or lands as noise.

    Devanagari must survive — stripping all non-ASCII would break the
    Hindi/Marathi packs the retrieval layer was built unicode-aware for.
    """
    assert llama_client.visible_text("Well done! 😊👍") == "Well done! "
    assert "पानी" in llama_client.visible_text("पानी 🌧 is water")


def test_semantic_falls_back_when_embedding_server_is_down(library):
    """No embedding server must degrade to lexical, never break the loop.

    The egg is offline-first; a retrieval backend being unreachable is a normal
    state, not an error. retrieve_semantic() returns None so the caller can
    fall back rather than losing retrieval entirely.
    """
    cfg = config.load(path=None)
    cfg["tutor"]["embed_url"] = "http://127.0.0.1:9"   # closed port
    assert library.retrieve_semantic("how does rain happen", cfg) is None
    assert library.retrieve("why does the plant not just eat the soil")


def test_no_embed_url_configured_is_not_an_error(library):
    cfg = config.load(path=None)
    cfg["tutor"]["embed_url"] = None
    assert library.retrieve_semantic("anything", cfg) is None
