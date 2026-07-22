import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[2] / "tools"))
import build_pack  # noqa: E402

from coco_egg.tutor.pack import Pack  # noqa: E402

DOC = """The sun heats water in rivers and seas. The water becomes vapour and rises.
This is called evaporation.

High in the sky the vapour cools down and forms clouds. This step is called
condensation. Clouds are made of tiny drops of water.

When the drops join and become heavy, they fall down as rain. This is called
precipitation. The rain fills the rivers again and the cycle repeats.
"""


def test_merge_paragraphs_respects_target():
    chunks = build_pack.merge_paragraphs(DOC, target=120)
    assert len(chunks) >= 2
    assert all("\n" not in c for c in chunks)
    # no paragraph is ever split, so every sentence survives somewhere
    assert any("precipitation" in c for c in chunks)


def test_slugify():
    assert build_pack.slugify("The Water Cycle!") == "the-water-cycle"
    assert build_pack.slugify("???") == "chunk"


def test_heuristic_build_loads_as_pack(tmp_path):
    pack_dict = build_pack.build(DOC, topic="Water", llm_url=None)
    assert pack_dict["lesson"] and len(pack_dict["lesson"]) == len(pack_dict["chunks"])
    path = tmp_path / "pack.json"
    import json
    path.write_text(json.dumps(pack_dict))
    pack = Pack.load(path)
    hits = pack.retrieve("why does rain fall from clouds")
    assert hits and "rain" in hits[0]["text"]
