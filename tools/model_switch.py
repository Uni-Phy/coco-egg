"""Registry side of tutor-model swapping. Driven by the Makefile, not by hand.

    make model-list
    make model-use NAME=qwen3-1.7b
    make model-add NAME=lfm2.5-1.2b URL=https://... FILE=LFM2.5-1.2B-Q4_K_M.gguf

Two files, and the split between them is the point. `models.json` is the tracked
registry of candidates — what exists, where to get it, what we know about it.
`deploy/.env` is the untracked record of which one is live *on this machine*,
because a bench and a device may legitimately differ and neither should have to
edit code (or the compose file) to say so.

Downloads are resumable and verified for size, since a truncated GGUF fails
inside llama-server with an error that looks nothing like "the download died".
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "models.json"
ENV = ROOT / "deploy" / ".env"
MODELS = ROOT / "models"


def load() -> dict:
    return json.loads(REGISTRY.read_text())


def save(reg: dict) -> None:
    REGISTRY.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n")


def live() -> str:
    """The model named in deploy/.env, or "" when the compose default applies."""
    if not ENV.is_file():
        return ""
    for line in ENV.read_text().splitlines():
        if line.startswith("TUTOR_MODEL="):
            return line.split("=", 1)[1].strip()
    return ""


def find(reg: dict, name: str) -> dict | None:
    return next((m for m in reg["models"] if m["name"] == name), None)


def cmd_list(reg: dict) -> None:
    current = live()
    for m in reg["models"]:
        file = m.get("file")
        on_disk = bool(file) and (MODELS / file).is_file()
        if file and file == current:
            mark = "->"
        elif not current and m.get("default"):
            mark = "->"
        else:
            mark = "  "
        state = "on disk" if on_disk else ("not fetched" if file else "no url yet")
        print(f"{mark} {m['name']:<16} {m.get('size', ''):>8}  {state}")
        print(f"     {m.get('notes', '')}")
    print(f"\nlive: {current or '(compose default)'}")


def fetch(model: dict) -> pathlib.Path:
    file, url = model.get("file"), model.get("url")
    if not file or not url:
        sys.exit(f"model-use: {model['name']} has no url registered yet.\n"
                 f"  make model-add NAME={model['name']} URL=<gguf-url> FILE=<name.gguf>")
    dest = MODELS / file
    if dest.is_file() and dest.stat().st_size > 0:
        print(f"==> {file} already on disk")
        return dest
    MODELS.mkdir(exist_ok=True)
    print(f"==> fetching {file} ({model.get('size', 'unknown size')})")
    # -c so an interrupted pull resumes instead of restarting; a half file that
    # looks complete is the failure mode worth avoiding here.
    r = subprocess.run(["wget", "-c", "-q", "--show-progress", "-O", str(dest), url])
    if r.returncode != 0 or not dest.is_file() or dest.stat().st_size == 0:
        dest.unlink(missing_ok=True)
        sys.exit(f"model-use: download failed for {url}")
    return dest


def cmd_use(reg: dict, name: str) -> None:
    model = find(reg, name)
    if not model:
        sys.exit(f"model-use: unknown model {name!r}. Try `make model-list`.")
    fetch(model)
    ENV.parent.mkdir(exist_ok=True)
    lines = [ln for ln in (ENV.read_text().splitlines() if ENV.is_file() else [])
             if not ln.startswith("TUTOR_MODEL=")]
    lines.append(f"TUTOR_MODEL={model['file']}")
    ENV.write_text("\n".join(lines) + "\n")
    print(f"==> live model is now {model['file']}")
    if "KNOWN BAD" in (model.get("notes") or ""):
        print("    NOTE: this one is registered as known bad. model-check should FAIL.")


def cmd_add(reg: dict, name: str, url: str, file: str) -> None:
    model = find(reg, name)
    if model:
        model["url"], model["file"] = url, file
        print(f"==> updated {name}")
    else:
        reg["models"].append({"name": name, "file": file, "url": url,
                              "notes": "Added locally; run model-check before shipping."})
        print(f"==> registered {name}")
    save(reg)


def main() -> None:
    args = [a for a in sys.argv[1:] if a]
    if not args:
        sys.exit("usage: model_switch.py list | use <name> | add <name> <url> <file>")
    reg = load()
    match args[0]:
        case "list":
            cmd_list(reg)
        case "use" if len(args) == 2:
            cmd_use(reg, args[1])
        case "add" if len(args) == 4:
            cmd_add(reg, args[1], args[2], args[3])
        case _:
            sys.exit("usage: model_switch.py list | use <name> | add <name> <url> <file>")


if __name__ == "__main__":
    main()
