"""The learner layer is schema-free, so these test that it stays that way."""
from coco_egg.tutor import profile


def test_unknown_keys_still_reach_the_prompt():
    """No field list: a preference nobody anticipated must still get through.

    This is the point of the layer — it should grow by editing YAML, not by
    editing code, so a test that pins a schema would defeat it.
    """
    out = profile.describe({"favourite_sport": "cricket", "reads_at": "grade 5"})
    assert "favourite sport: cricket" in out
    assert "reads at: grade 5" in out


def test_lists_and_nesting_render():
    out = profile.describe({"interests": ["farming", "cricket"],
                            "pace": {"new_topics": "slow"}})
    assert "farming, cricket" in out
    assert "new topics: slow" in out


def test_empty_values_are_dropped():
    """A half-filled profile should read short, not as a list of blanks."""
    assert profile.describe({"name": "Asha", "grade": "", "interests": []}) == "- name: Asha"


def test_no_profile_is_empty_string():
    assert profile.describe({}) == ""


def test_inline_learner_block_is_used_when_no_file():
    cfg = {"tutor": {"profile": "does-not-exist.yaml"}, "learner": {"grade": "6"}}
    assert profile.load(cfg) == {"grade": "6"}


def test_missing_everything_is_empty():
    assert profile.load({"tutor": {}}) == {}
