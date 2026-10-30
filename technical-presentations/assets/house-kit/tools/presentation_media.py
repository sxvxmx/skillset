#!/usr/bin/env python3
"""Optional DeckCraft export and offline player for any manifest's videos."""
import argparse
import base64
from html import escape
import json
import os
from pathlib import Path
import shutil
import subprocess

from presentation import read_manifest, require, check_delivery


def commands(cli, source, operations, save=None):
    args = [cli,"run","--in",str(source),"--print"]
    for name, arguments in operations:
        args.extend(["--cmd",name+"="+json.dumps(arguments)])
    if save:
        args.extend(["--save",str(save)])
    response = subprocess.run(args, check=True, capture_output=True, text=True, timeout=120)
    results = {}
    for line in response.stdout.splitlines():
        if " → " in line:
            name, value = line.split(" → ",1)
            results[name] = json.loads(value)
    return results


def export(manifest, executable=None):
    data = read_manifest(manifest); folder = Path(manifest).resolve().parent
    check_delivery(manifest)
    cli = executable or os.environ.get("DECKCRAFT_CLI") or shutil.which("deckcraft-cli")
    require(cli, "set DECKCRAFT_CLI or pass --cli with the official DeckCraft CLI path")
    source = folder/"dist"/"slides.pptx"; target = source.with_suffix(".deckcraft")
    videos = [(n, s) for n,s in enumerate(data["slides"],1) if s.get("video")]
    operations = []; ids = {}
    for n,slide in videos:
        info = commands(cli,source,[("slide.inspect",{"index":n-1})])["slide.inspect"]
        shapes = [s for s in info["shapes"] if s["kind"] == "video"]
        require(len(shapes) == 1, f"slide {n}: expected one video")
        ids[n] = shapes[0]["id"]
        operations.extend([("slide.go",{"index":n-1}),
                           ("media.options",{"ids":[ids[n]],"autoplay":True,"loop":False,"rewind":False,"volume":0,"hide":False})])
    # Always inspect at least the first slide, including decks without video.
    commands(cli,source,operations or [("slide.inspect",{"index":0})],target)
    document = json.loads(subprocess.check_output([cli,"info",str(target)],text=True))
    require(all(not s["notes"] for s in document["slides"]), "native deck contains speaker notes")
    checks = {}; sections = []
    for n, slide in videos:
        info = commands(cli,target,[("slide.go",{"index":n-1}),("media.info",{"id":ids[n]})])["media.info"]
        require(info["options"]["autoplay"] and info["probe"]["playable"], f"slide {n}: playback options invalid")
        require(info["probe"]["video"]["decodable"], f"slide {n}: decoder rejected video")
        duration = info["probe"]["durationMs"]; ms = min(4000,max(0,duration//2))
        commands(cli,target,[("slide.go",{"index":n-1}),("media.posterFrame",{"id":ids[n],"ms":ms})])
        checks[n] = {"autoplay":True,"decoded_frame_ms":ms,"probe":info["probe"]}
        encoded = base64.b64encode((folder/slide["video"]).read_bytes()).decode()
        sections.append(f'<section><h2>Слайд {n}. {escape(slide["title"])}</h2>'
                        f'<p>{escape(slide["image"]["description"])}</p>'
                        f'<video controls preload="metadata" playsinline src="data:video/mp4;base64,{encoded}"></video></section>')
    if sections:
        html = '<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
        html += '<title>'+escape(data["brief"]["title"])+" — видео</title>"
        html += '<style>body{font:18px/1.5 Arial,sans-serif;color:#161616;background:white;max-width:1100px;margin:32px auto;padding:0 24px}h1,h2{font-weight:400}section{margin:45px 0}video{width:100%;max-height:75vh}</style>'
        html += '<h1>'+escape(data["brief"]["title"])+"</h1><p>Клипы встроены в эту страницу. Нажмите ▶ для воспроизведения.</p>"+"".join(sections)+"</html>"
        (folder/"dist"/"animations.html").write_text(html)
    version = subprocess.check_output([cli,"--version"],text=True).strip()
    (folder/"qa"/"media-checks.json").write_text(json.dumps({"cli":version,"slides":checks,
        "native_notes":0,"live_playback":"requires a separate check in slideshow mode"},ensure_ascii=False,indent=2))
    print(f"{version}: native deck, {len(videos)} autoplay videos decoded. Test slideshow playback before presenting.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest"); parser.add_argument("--cli")
    args = parser.parse_args()
    export(args.manifest,args.cli)
