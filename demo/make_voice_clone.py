"""Voice-over in a cloned voice (local, offline): Coqui XTTS-v2 conditioned on a short reference clip.

Run with the separate voice venv (heavy deps stay out of the project requirements):

  demo/.voice-venv/Scripts/python.exe demo/make_voice_clone.py --test           # one short test line -> demo/voice-test.wav
  demo/.voice-venv/Scripts/python.exe demo/make_voice_clone.py                  # every `say` line of all 3 scenarios
  options: --ref demo/voice-ref/ref.wav  --speed 1.0

Writes voice/<scenario>/NN.mp3 + attaches `"audio"` to each spoken step (same layout as make_voice.py), so
`npx agent-screenplay render <scenario>.json` uses them. Reference audio never leaves this machine.
XTTS-v2 is under the Coqui Public Model License (non-commercial): fine for a hackathon demo.
"""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENARIOS = ["01-problem.json", "02-slack.json", "03-board.json"]
FFMPEG = Path.home() / "AppData/Roaming/npm/node_modules/agent-screenplay/node_modules/ffmpeg-static/ffmpeg.exe"


def opt(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def load_model():
    import torch
    from TTS.api import TTS
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"loading XTTS-v2 on {dev} ...")
    return TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(dev)


def spoken(text: str) -> str:
    """Light normalisation so numbers and symbols are read naturally."""
    t = text.replace("£", "pounds ").replace("&", " and ")
    return re.sub(r"\s+", " ", t).strip()


def synth(tts, text, ref, speed, out_wav):
    # XTTS handles one sentence group at a time best; split long lines on sentence ends.
    tts.tts_to_file(text=spoken(text), speaker_wav=str(ref), language="en", file_path=str(out_wav), speed=speed,
                    split_sentences=True)


def to_mp3(wav, mp3):
    subprocess.run([str(FFMPEG), "-loglevel", "error", "-y", "-i", str(wav), "-ar", "44100", "-ac", "1",
                    "-af", "loudnorm=I=-18:TP=-2", "-b:a", "128k", str(mp3)], check=True)


def main():
    ref = Path(opt("--ref", str(HERE / "voice-ref" / "ref.wav")))
    speed = float(opt("--speed", "1.0"))
    if not ref.exists():
        raise SystemExit(f"reference clip not found: {ref}")
    tts = load_model()
    if "--test" in sys.argv:
        line = ("This is Margaret. She's eighty-two, and at ten this morning her doctor said she was well enough "
                "to go home.")
        out = HERE / "voice-test.wav"
        synth(tts, line, ref, speed, out)
        print(f"wrote {out}")
        return
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
            mp3, tag = outdir / f"{n:02d}.mp3", outdir / f"{n:02d}.sha"
            digest = hashlib.sha256(f"xtts|{ref.stat().st_size}|{speed}|{text}".encode()).hexdigest()
            if not (mp3.exists() and tag.exists() and tag.read_text() == digest):
                wav = outdir / f"{n:02d}.wav"
                synth(tts, text, ref, speed, wav)
                to_mp3(wav, mp3)
                wav.unlink()
                tag.write_text(digest)
                print(f"  {name} #{n}: cloned ({len(text)} chars)")
            step["audio"] = f"voice/{path.stem}/{n:02d}.mp3"
        scen.setdefault("voice", {})["enabled"] = True
        path.write_text(json.dumps(scen, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{name}: {n} spoken steps")


if __name__ == "__main__":
    main()
