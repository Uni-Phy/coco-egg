#!/usr/bin/env python3
"""Build a coco-egg content pack from a document (node-side tool).

Turns a .txt/.md/.pdf into the pack JSON the device tutor grounds on
(device/coco_egg/tutor/pack.py). Heuristic mode needs nothing beyond the
stdlib; --llm additionally polishes every chunk — a concise title, a spoken
explanation, a lesson goal — through an OpenAI-compatible server: llama-server
on the bench, the big model on the CoCo node in production.

    python tools/build_pack.py topic.txt -o fixtures/topic-pack.json
    python tools/build_pack.py topic.pdf --llm http://127.0.0.1:8080

PDF input needs pypdf (pip install pypdf). This tool never runs on the
device; the device only ever loads the finished JSON.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import urllib.request

CHUNK_TARGET_CHARS = 700
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def read_document(path: pathlib.Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            sys.exit("PDF input needs pypdf: pip install pypdf")
        return "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    return path.read_text()


def merge_paragraphs(text: str, target: int = CHUNK_TARGET_CHARS) -> list[str]:
    """Merge paragraphs into chunks of roughly `target` chars, never splitting one."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    current = ""
    for p in paras:
        p = re.sub(r"\s+", " ", p)
        if current and len(current) + len(p) > target:
            chunks.append(current)
            current = p
        else:
            current = f"{current} {p}".strip()
    if current:
        chunks.append(current)
    return chunks


def slugify(title: str) -> str:
    return re.sub(r"[^\w]+", "-", title.lower()).strip("-")[:40] or "chunk"


def heuristic_chunk(text: str, index: int) -> dict:
    """No-LLM chunk: first few words become the title, first sentences the explain."""
    sentences, rest = _SENTENCE_END.split(text + " ")[:-1], _SENTENCE_END.split(text + " ")[-1]
    title = " ".join(text.split()[:5])
    explain = " ".join(sentences[:3]).strip() or text
    return {"id": f"{index:02d}-{slugify(title)}", "title": title,
            "text": text, "explain": explain}


def llm_polish(chunk: dict, url: str) -> dict:
    """Ask the LLM for a concise title + spoken explanation + lesson goal."""
    prompt = (
        "Material:\n" + chunk["text"] + "\n\n"
        'Reply with JSON only, no other text: {"title": "<concept name, 2-4 words>", '
        '"explain": "<explain the material for a middle-school student in at most '
        '3 short simple sentences, as if speaking aloud>", '
        '"goal": "<one sentence: what the student should understand>"}'
    )
    body = json.dumps({
        "temperature": 0.3,
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {"role": "system",
             "content": "You create teaching material for a voice tutor for school children."},
            {"role": "user", "content": prompt},
        ],
    }).encode()
    req = urllib.request.Request(f"{url}/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        content = json.load(resp)["choices"][0]["message"]["content"]
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL)
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if not match:
        print(f"  warn: no JSON from LLM for {chunk['id']}, keeping heuristic")
        return chunk
    try:
        polished = json.loads(match.group())
    except json.JSONDecodeError:
        print(f"  warn: bad JSON from LLM for {chunk['id']}, keeping heuristic")
        return chunk
    out = dict(chunk)
    out["title"] = polished.get("title") or chunk["title"]
    out["explain"] = polished.get("explain") or chunk["explain"]
    if polished.get("goal"):
        out["goal"] = polished["goal"]
    out["id"] = slugify(out["title"])
    return out


def build(text: str, topic: str, llm_url: str | None) -> dict:
    chunks = [heuristic_chunk(c, i) for i, c in enumerate(merge_paragraphs(text))]
    if llm_url:
        for i, c in enumerate(chunks):
            print(f"  polishing {i + 1}/{len(chunks)}: {c['id']}")
            chunks[i] = llm_polish(c, llm_url)
    for c in chunks:
        c.pop("_tokens", None)
    lesson = [{"id": c["id"], "goal": c.get("goal", f"Understand {c['title']}.")}
              for c in chunks]
    for c in chunks:
        c.pop("goal", None)
    return {"topic": topic, "lesson": lesson, "chunks": chunks}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("document", help=".txt/.md/.pdf source")
    ap.add_argument("-o", "--output", help="pack JSON path (default: <doc>-pack.json)")
    ap.add_argument("--topic", help="pack topic label (default: document name)")
    ap.add_argument("--llm", metavar="URL", default=None,
                    help="OpenAI-compatible server for polish (e.g. http://127.0.0.1:8080)")
    args = ap.parse_args()

    src = pathlib.Path(args.document)
    out = pathlib.Path(args.output or src.with_suffix("").name + "-pack.json")
    pack = build(read_document(src), args.topic or src.stem, args.llm)
    out.write_text(json.dumps(pack, ensure_ascii=False, indent=2) + "\n")
    print(f"wrote {out}: {len(pack['chunks'])} chunks, "
          f"{len(pack['lesson'])} lesson steps")


if __name__ == "__main__":
    main()
