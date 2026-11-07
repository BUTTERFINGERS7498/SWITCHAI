"""Generate the demo voice-over with a free Microsoft neural voice (edge-tts) and attach one file per spoken step.

  .venv/Scripts/python.exe demo/make_voice.py [--voice en-GB-SoniaNeural] [--rate +0%]

For every scenario in demo/ (01-problem, 02-slack, 03-board): each step with `say` gets
voice/<scenario>/NN.mp3 and `"audio": "voice/<scenario>/NN.mp3"`; `voice.enabled` is set to true.
Screenplay then uses these files instead of a paid TTS key (`npx agent-screenplay render <scenario>`).
Files are regenerated only when the text, voice or rate changes.
"""
import asyncio
import hashlib
import json
import sys
from pathlib import Path

import edge_tts

HERE = Path(__file__).resolve().parent
SCENARIOS = ["01-problem.json", "02-slack.json", "03-board.json"]


def opt(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


async def main():
    voice, rate = opt("--voice", "en-GB-SoniaNeural"), opt("--rate", "+0%")
    for name in SCENARIOS:
        path = HERE / name
        scen = json.loads(path.read_text(encoding="utf-8"))
        outdir = HERE / "voice" / path.stem
        outdir.mkdir(parents=True, exist_ok=True)
        n = 0
        for step in scen["steps"]:
            text = step.get("say")
            if not text:
                step.pop("audio", None)
                continue
            n += 1
            mp3 = outdir / f"{n:02d}.mp3"
            tag = outdir / f"{n:02d}.sha"
            digest = hashlib.sha256(f"{voice}|{rate}|{text}".encode()).hexdigest()
            if not (mp3.exists() and tag.exists() and tag.read_text() == digest):
                await edge_tts.Communicate(text, voice, rate=rate).save(str(mp3))
                tag.write_text(digest)
                print(f"  {name} #{n}: generated ({len(text)} chars)")
            step["audio"] = f"voice/{path.stem}/{n:02d}.mp3"
        scen.setdefault("voice", {})["enabled"] = True
        path.write_text(json.dumps(scen, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{name}: {n} spoken steps, voice {voice}")


asyncio.run(main())
