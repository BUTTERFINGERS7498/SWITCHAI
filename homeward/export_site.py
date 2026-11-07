"""Static replay site (for GitHub Pages): the real board page, driven by recorded simulator snapshots.

  python scripts/homeward.py site        ->  docs/index.html  (one self-contained file)

The page is homeward/sim/static/board.html unchanged, plus an injected script that answers the board's
three requests (/board/ward, /patients/N/handover, /patients/N/ledger) from snapshots taken by replaying
Margaret's day through the same Store operations as `scenario margaret --auto`, and a small replay bar.
Nothing is faked in the page: every card, ledger line and handover is simulator output.
"""
from __future__ import annotations

import json
from pathlib import Path

from homeward.sim import demo, seed

ROOT = Path(__file__).resolve().parent.parent
BOARD = ROOT / "homeward" / "sim" / "static" / "board.html"
OUT = ROOT / "docs" / "index.html"


def snapshot(s, label: str) -> dict:
    from homeward import engine as e
    board = s.board()
    handover, ledger = {}, {}
    for bed, plan in s.plans.items():
        handover[str(bed)] = e.handover_summary(plan, s.clock)
        ledger[str(bed)] = s.ledger_view(bed)
    return {"label": label, "board": board, "handover": handover, "ledger": ledger}


def frames() -> list[dict]:
    s = seed.build("margaret")
    out = [snapshot(s, "10:00 · The ward at the start of the day. Margaret (bed 12) has not yet been declared fit.")]
    done = 0
    while done < len(demo.BEATS):
        done, label = demo.next_beat(s, done)
        out.append(snapshot(s, label))
    return out


INJECT = r"""
<script>
window.__HW_FRAMES = %FRAMES%;
(function () {
  let i = 0, timer = null;
  const F = window.__HW_FRAMES, N = F.length - 1;
  const json = o => new Response(JSON.stringify(o), { status: 200, headers: { "content-type": "application/json" } });
  const text = t => new Response(t, { status: 200, headers: { "content-type": "text/plain" } });
  const real = window.fetch.bind(window);
  window.fetch = async (url, opts) => {
    const u = String(url), post = opts && opts.method === "POST";
    if (u.endsWith("/board/ward")) return json(F[i].board);
    let m = u.match(/\/patients\/(\d+)\/handover$/);
    if (m) return F[i].handover[m[1]] ? text(F[i].handover[m[1]]) : new Response("{}", { status: 404 });
    m = u.match(/\/patients\/(\d+)\/ledger$/);
    if (m) return F[i].ledger[m[1]] ? json(F[i].ledger[m[1]]) : new Response("[]", { status: 404 });
    if (post && u.endsWith("/demo/next")) { go(i + 1); return json({}); }
    if (post && u.endsWith("/reset")) { go(0); return json({}); }
    return real(url, opts);
  };
  const bar = document.createElement("div");
  bar.setAttribute("role", "region"); bar.setAttribute("aria-label", "Replay controls");
  bar.style.cssText = "position:fixed;left:0;right:0;bottom:0;z-index:50;display:flex;gap:10px;align-items:center;flex-wrap:wrap;" +
    "padding:10px clamp(12px,3vw,32px);background:var(--ink);color:var(--panel);font:600 .95rem system-ui,sans-serif;box-shadow:0 -4px 20px rgba(0,0,0,.25)";
  bar.innerHTML = '<span id="rp-step" style="opacity:.8;white-space:nowrap"></span><span id="rp-label" style="flex:1;min-width:220px"></span>' +
    '<button id="rp-back" class="tool rp">◀ Back</button><button id="rp-next" class="tool rp">Next ▶</button>' +
    '<button id="rp-play" class="tool rp">▶ Play the day</button><button id="rp-reset" class="tool rp">↺ Restart</button>' +
    '<a href="https://github.com/BUTTERFINGERS7498/SWITCHAI" style="color:inherit;margin-left:6px">GitHub ↗</a>';
  const st = document.createElement("style");
  st.textContent = ".live{display:none!important} .tool.rp{color:#14212b;background:#fffdf9;font-weight:650} .tool.rp:disabled{opacity:.45;cursor:default}";
  document.head.appendChild(st);
  document.body.appendChild(bar);
  document.body.style.paddingBottom = "96px";
  const $ = id => document.getElementById(id);
  function go(n) {
    i = Math.max(0, Math.min(N, n));
    $("rp-step").textContent = "Replay " + i + " / " + N;
    $("rp-label").textContent = F[i].label;
    $("rp-back").disabled = i === 0; $("rp-next").disabled = i === N;
    if (i === N) stop();
    if (typeof tick === "function") tick();
  }
  function stop() { if (timer) { clearInterval(timer); timer = null; } $("rp-play").textContent = "▶ Play the day"; }
  $("rp-next").onclick = () => { stop(); go(i + 1); };
  $("rp-back").onclick = () => { stop(); go(i - 1); };
  $("rp-reset").onclick = () => { stop(); go(0); };
  $("rp-play").onclick = () => {
    if (timer) return stop();
    if (i === N) go(0);
    $("rp-play").textContent = "❚❚ Pause";
    timer = setInterval(() => go(i + 1), 3200);
  };
  go(0);
})();
</script>
"""


def build() -> Path:
    html = BOARD.read_text(encoding="utf-8")
    fr = json.dumps(frames(), ensure_ascii=False, default=str).replace("</", "<\\/")
    html = html.replace("<title>Ward 7 · Homeward</title>", "<title>Homeward · replay of Margaret's day</title>")
    marker = "<script>\n\"use strict\";"
    assert marker in html, "board.html script marker not found"
    html = html.replace(marker, INJECT.replace("%FRAMES%", fr) + marker, 1)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    return OUT


if __name__ == "__main__":
    p = build()
    print(f"wrote {p} ({p.stat().st_size // 1024} KB)")
