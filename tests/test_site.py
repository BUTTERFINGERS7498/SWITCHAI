import json
import re

from homeward import export_site


def test_replay_frames_follow_the_day():
    fr = export_site.frames()
    assert len(fr) == 7 and fr[0]["label"].startswith("10:00")
    assert fr[3]["label"].startswith("11:00") and fr[4]["label"].startswith("11:20")
    bed12 = lambda f: next(b for b in f["board"]["beds"] if b["bed"] == 12)
    assert not bed12(fr[0])["declared_fit"] and bed12(fr[1])["declared_fit"]
    assert any(t["status"] == "blocked" for t in bed12(fr[4])["tasks"])      # the 11:20 cancellation
    last = fr[-1]
    assert bed12(last)["departed_at"].endswith("12:40:00+00:00")
    assert last["board"]["totals"]["hours_freed"] == 6.5 and last["board"]["totals"]["clinical_by_agents"] == 0
    assert "went home at 12:40" in last["handover"]["12"]


def test_site_is_one_self_contained_file(tmp_path, monkeypatch):
    monkeypatch.setattr(export_site, "OUT", tmp_path / "index.html")
    html = export_site.build().read_text(encoding="utf-8")
    m = re.search(r"window\.__HW_FRAMES = (\[.*?\]);\n", html, re.S)
    assert m and len(json.loads(m.group(1))) == 7
    assert "<title>Homeward · replay of Margaret's day</title>" in html
    assert 'src="http' not in html and "href=\"http" not in html.replace("https://github.com/BUTTERFINGERS7498/SWITCHAI", "")
