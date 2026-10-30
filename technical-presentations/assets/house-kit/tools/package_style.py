#!/usr/bin/env python3
"""Package the general style and tools, without topic-specific deliverables."""
import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parent.parent


def package(output, example=None):
    paths = [ROOT/name for name in ("PRESENTATION_GUIDE.md","GUIDE_CHANGELOG.md",
                                   "guideline.yaml","pyproject.toml","uv.lock")]
    paths += [path for path in (ROOT/"templates"/"presentation").rglob("*") if path.is_file()]
    paths += [path for path in (ROOT/"fonts").rglob("*") if path.is_file()]
    for path in (ROOT/"tools").rglob("*.py"):
        if "__pycache__" not in path.parts and path.name not in {"build_deck.py"}:
            paths.append(path)
    entries = {str(path.relative_to(ROOT)):path for path in paths}
    if example:
        example = Path(example).resolve()
        for name in ("deck.yaml","README.md","dist/slides.pptx","dist/slides.pdf","dist/speaker-script.pdf"):
            path = example/name
            if not path.is_file():
                raise ValueError(f"example file missing: {path}")
            entries[f"examples/style-demo/{name}"] = path
    output = Path(output).resolve(); output.parent.mkdir(parents=True,exist_ok=True)
    manifest = {}
    with ZipFile(output,"w",ZIP_DEFLATED,compresslevel=6) as archive:
        for name,path in sorted(entries.items()):
            data = path.read_bytes(); archive.writestr("presentation-style-kit/"+name,data)
            manifest[name] = {"bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()}
        archive.writestr("presentation-style-kit/manifest.json",json.dumps(manifest,ensure_ascii=False,indent=2))
    with ZipFile(output) as archive:
        assert archive.testzip() is None
        for name,meta in manifest.items():
            assert hashlib.sha256(archive.read("presentation-style-kit/"+name)).hexdigest() == meta["sha256"]
    print(f"{output}: {len(entries)} files, {output.stat().st_size/1048576:.1f} MiB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",default=str(ROOT/"dist/presentation-style-kit.zip"))
    parser.add_argument("--example")
    args = parser.parse_args(); package(args.output,args.example)
