"""Natural voice-over in YOUR timbre: a neural Indian-English voice (edge-tts) supplies rhythm, intonation and
accent; FreeVC24 voice conversion (coqui-tts) then re-voices it to match a short reference clip. Offline conversion;
only the narration text goes to Microsoft's speech service for the base audio.

  demo/.voice-venv/Scripts/python.exe demo/make_voice_vc.py --test [--base en-IN-PrabhatNeural] [--rate -4%]
  demo/.voice-venv/Scripts/python.exe demo/make_voice_vc.py            # all spoken lines of the 3 scenarios

Writes voice/<scenario>/NN.mp3 and sets each spoken step's "audio" (same layout as make_voice.py).
"""
import asyncio
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCENARIOS = ["01-problem.json", "02-slack.json", "03-board.json"]
FFMPEG = Path.home() / "AppData/Roaming/npm/node_modules/agent-screenplay/node_modules/ffmpeg-static/ffmpeg.exe"
TEST_LINE = ("This is Margaret. She's eighty-two, and at ten this morning her doctor said she was well enough "
             "to go home.")


def opt(name, default):
    return sys.argv[sys.argv.index(name) + 1] if name in sys.argv else default


def ff(*args):
    subprocess.run([str(FFMPEG), "-loglevel", "error", "-y", *args], check=True)


async def base_audio(text, voice, rate, out_mp3):
    import edge_tts
    await edge_tts.Communicate(text, voice, rate=rate).save(str(out_mp3))


def say_text(t):
    return re.sub(r"\s+", " ", t.replace("£", "pounds ").replace("&", " and ")).strip()


def main():
    base, rate = opt("--base", "en-IN-PrabhatNeural"), opt("--rate", "-4%")
    ref = Path(opt("--ref", str(HERE / "voice-ref" / "ref.wav")))
    import torch
    from TTS.api import TTS
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"loading FreeVC24 on {dev} ...")
    vc = TTS("voice_conversion_models/multilingual/vctk/freevc24").to(dev)
    tmp = HERE / "voice" / "_tmp"
    tmp.mkdir(parents=True, exist_ok=True)

    def convert(text, out_wav):
        src_mp3, src_wav = tmp / "base.mp3", tmp / "base.wav"
        asyncio.run(base_audio(say_text(text), base, rate, src_mp3))
        ff("-i", str(src_mp3), "-ar", "24000", "-ac", "1", str(src_wav))
        vc.voice_conversion_to_file(source_wav=str(src_wav), target_wav=str(ref), file_path=str(out_wav))

    def finish(wav, mp3):
        ff("-i", str(wav), "-ar", "44100", "-ac", "1",
           "-af", "highpass=f=60,loudnorm=I=-18:TP=-2:LRA=7", "-b:a", "160k", str(mp3))

    if "--test" in sys.argv:
        out = HERE / "voice-test-vc.wav"
        convert(TEST_LINE, out)
        finish(out, HERE / "voice-test-vc.mp3")
        print(f"wrote {out.with_suffix('.mp3')}")
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
            digest = hashlib.sha256(f"vc|{base}|{rate}|{ref.stat().st_size}|{text}".encode()).hexdigest()
            if not (mp3.exists() and tag.exists() and tag.read_text() == digest):
                wav = outdir / f"{n:02d}.wav"
                convert(text, wav)
                finish(wav, mp3)
                wav.unlink()
                tag.write_text(digest)
                print(f"  {name} #{n}: done ({len(text)} chars)")
            step["audio"] = f"voice/{path.stem}/{n:02d}.mp3"
        scen.setdefault("voice", {})["enabled"] = True
        path.write_text(json.dumps(scen, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{name}: {n} spoken steps")


if __name__ == "__main__":
    main()
