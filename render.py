"""main.py が取得した結果 (SourceResult のリスト) から、直近1週間分の
社説ダイジェストをまとめたモバイル向けWebページ (output/digest.html) を
生成するモジュール。

全国紙（tier: national）を既定表示、ブロック紙（tier: block）・地方紙
（tier: regional）はページ内のチップボタンでそれぞれ独立に表示切り替え
できる構成。外部CDN・Webフォントは使わず自己完結。
"""
from __future__ import annotations

import html
from collections import defaultdict
from datetime import date

from pubdate import parse_published_date, parse_published_time

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]
TIERS = ["national", "block", "regional"]
TIER_LABEL = {"national": "全国紙", "block": "ブロック紙", "regional": "地方紙"}

# ダークモード両対応・自己完結のCSS。f-string化するとブレースの二重化が
# 必要になり可読性が落ちるため、動的な値を含まないこのブロックだけ独立した
# 通常の文字列にしている。
_CSS = """
:root {
  --bg:#F1F2EC; --surface:#FFFFFF; --ink:#1C1E1B; --ink-muted:#63665D; --ink-faint:#8A8D82;
  --accent:#1B4B6B; --accent-soft:#E3EAEE; --rule:#D9DAD2;
  --warn:#9C6B22; --warn-soft:#F3E9D8; --danger:#A23B3B; --danger-soft:#F5E4E1;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg:#14161A; --surface:#1C1F23; --ink:#E9EAE4; --ink-muted:#A2A69B; --ink-faint:#787C72;
    --accent:#7FB2D6; --accent-soft:#233642; --rule:#2B2F31;
    --warn:#D6A855; --warn-soft:#332A18; --danger:#D98F8F; --danger-soft:#3A2222;
  }
}
:root[data-theme="dark"] {
  --bg:#14161A; --surface:#1C1F23; --ink:#E9EAE4; --ink-muted:#A2A69B; --ink-faint:#787C72;
  --accent:#7FB2D6; --accent-soft:#233642; --rule:#2B2F31;
  --warn:#D6A855; --warn-soft:#332A18; --danger:#D98F8F; --danger-soft:#3A2222;
}
:root[data-theme="light"] {
  --bg:#F1F2EC; --surface:#FFFFFF; --ink:#1C1E1B; --ink-muted:#63665D; --ink-faint:#8A8D82;
  --accent:#1B4B6B; --accent-soft:#E3EAEE; --rule:#D9DAD2;
  --warn:#9C6B22; --warn-soft:#F3E9D8; --danger:#A23B3B; --danger-soft:#F5E4E1;
}
* { box-sizing: border-box; }
html, body { margin:0; padding:0; }
body {
  background: var(--bg); color: var(--ink);
  font-family: "Hiragino Sans","Yu Gothic","Noto Sans JP","Meiryo",system-ui,sans-serif;
  font-size: 16px; line-height: 1.7; -webkit-font-smoothing: antialiased; overflow-x: hidden;
}
.wrap { max-width: 640px; margin: 0 auto; padding: 0 0 4rem; }
header.masthead { padding: 2.25rem 1.25rem 1.25rem; border-bottom: 1px solid var(--rule); }
.eyebrow { font-size: 0.72rem; letter-spacing: 0.14em; color: var(--ink-faint); text-transform: uppercase; margin: 0 0 0.5rem; }
h1 {
  font-family: "Hiragino Mincho ProN","Yu Mincho","Noto Serif JP",serif;
  font-weight: 600; font-size: 1.85rem; line-height: 1.35; margin: 0 0 0.65rem; text-wrap: balance; letter-spacing: 0.01em;
}
.summary { display:flex; flex-wrap:wrap; gap:0.4rem 0.6rem; align-items:baseline; color:var(--ink-muted); font-size:0.92rem; margin:0 0 0.9rem; }
.summary strong { color: var(--ink); font-variant-numeric: tabular-nums; }
.disclaimer { font-size:0.82rem; color:var(--ink-faint); margin:0 0 1rem; line-height:1.6; }

.scope-toggle {
  background: var(--surface); border: 1px solid var(--rule); border-radius: 10px;
  padding: 0.7rem 0.9rem;
}
.scope-toggle .scope-label {
  display: block; font-size: 0.72rem; letter-spacing: 0.06em; color: var(--ink-faint);
  margin: 0 0 0.55rem;
}
.tier-chips { display: flex; gap: 0.5rem; flex-wrap: wrap; }
button.tier-chip {
  flex: 1 1 auto; font: inherit; font-size: 0.82rem; font-weight: 600;
  padding: 0.5rem 0.7rem; border-radius: 8px; border: 1px solid var(--accent);
  background: transparent; color: var(--accent); cursor: pointer;
  white-space: nowrap; display: inline-flex; align-items: baseline; justify-content: center; gap: 0.35rem;
}
button.tier-chip .tier-chip-count { font-size: 0.72rem; opacity: 0.75; font-variant-numeric: tabular-nums; }
button.tier-chip:hover { background: var(--accent-soft); }
button.tier-chip[aria-pressed="true"] { background: var(--accent); color: var(--surface); }
button.tier-chip:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

nav.quicknav {
  position: sticky; top: 0; z-index: 5; background: var(--bg);
  border-bottom: 1px solid var(--rule); padding: 0.6rem 0; overflow-x: auto;
  white-space: nowrap; -webkit-overflow-scrolling: touch; scrollbar-width: none;
}
nav.quicknav::-webkit-scrollbar { display: none; }
nav.quicknav .pill-row { display: inline-flex; gap: 0.5rem; padding: 0 1.25rem; }
.pill {
  display: inline-flex; align-items: baseline; gap: 0.3rem; padding: 0.38rem 0.75rem;
  border-radius: 999px; background: var(--surface); border: 1px solid var(--rule);
  color: var(--ink); text-decoration: none; font-size: 0.82rem; flex: none;
  font-variant-numeric: tabular-nums;
}
.pill-count { color: var(--ink-faint); font-size: 0.74rem; }

main { padding: 0 1.25rem; }

section.dategroup { padding: 1.6rem 0; border-bottom: 1px solid var(--rule); scroll-margin-top: 3.2rem; }
section.dategroup:last-child { border-bottom: none; }

.date-head { display:flex; align-items:baseline; gap:0.6rem; margin-bottom:0.15rem; }
.date-head h2 {
  font-family: "Hiragino Mincho ProN","Yu Mincho","Noto Serif JP",serif;
  font-weight:600; font-size:1.5rem; margin:0; color:var(--accent); font-variant-numeric: tabular-nums;
}
.date-head h2 .slash { color: var(--ink-faint); font-weight: 400; padding: 0 0.05rem; }
.date-head h2 .wd { font-size: 0.95rem; color: var(--ink-faint); font-family: "Hiragino Sans","Yu Gothic",sans-serif; font-weight:400; }
.date-count { font-size:0.78rem; color:var(--ink-faint); font-variant-numeric: tabular-nums; }
.latest-flag {
  font-size:0.7rem; color:var(--accent); border:1px solid var(--accent); border-radius:4px;
  padding:0.02rem 0.4rem; letter-spacing:0.04em;
}
.special-h { color: var(--ink-muted) !important; font-size:1.15rem !important; }

ul.article-list { list-style:none; margin:0.6rem 0 0; padding:0; }
ul.article-list li { border-top:1px solid var(--rule); }
ul.article-list li:first-child { border-top:none; }
body:not(.show-national) li.tier-national { display: none; }
body:not(.show-block) li.tier-block { display: none; }
body:not(.show-regional) li.tier-regional { display: none; }

body:not(.show-national) .special-national { display: none; }
body:not(.show-block) .special-block { display: none; }
body:not(.show-regional) .special-regional { display: none; }

a.article {
  display:flex; justify-content:space-between; align-items:flex-start; gap:0.9rem;
  padding:0.72rem 0.15rem; text-decoration:none; color:var(--ink); min-height:44px;
}
a.article:hover .article-title, a.article:focus-visible .article-title { color: var(--accent); }
a.article:focus-visible { outline:2px solid var(--accent); outline-offset:2px; border-radius:3px; }
.article-main { display:flex; flex-direction:column; gap:0.25rem; flex:1 1 auto; }
.src-tag {
  font-size:0.72rem; color:var(--accent); background:var(--accent-soft);
  border-radius:4px; padding:0.05rem 0.4rem; width:fit-content; letter-spacing:0.02em;
}
.src-tag-block { color: var(--accent); background: transparent; border: 1px solid var(--accent); }
.src-tag-regional { color: var(--ink-muted); background: transparent; border: 1px solid var(--rule); }
.article-title { font-size:0.98rem; line-height:1.55; }
.paid-badge {
  font-size:0.68rem; color: var(--warn); border: 1px solid var(--warn); border-radius: 4px;
  padding: 0 0.3rem; margin-left: 0.4rem; letter-spacing: 0.02em; white-space: nowrap;
  vertical-align: 0.1em;
}
a.article time {
  flex:none; font-size:0.76rem; color:var(--ink-faint); font-variant-numeric: tabular-nums;
  white-space:nowrap; padding-top:0.2rem;
}

.note { margin:0.6rem 0 0; padding:0.7rem 0.85rem; border-radius:6px; font-size:0.88rem; line-height:1.6; }
.note-skip { background: var(--warn-soft); color: var(--warn); }
.note-error { background: var(--danger-soft); color: var(--danger); }

footer { padding:1.75rem 1.25rem 0; color:var(--ink-faint); font-size:0.78rem; line-height:1.7; }
html { scroll-behavior: smooth; }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
"""

_SCRIPT_TEMPLATE = """
(function () {
  var TIERS = ['national', 'block', 'regional'];
  var DEFAULT_ON = { national: true, block: false, regional: false };
  var body = document.body;
  var totalEl = document.getElementById('total-count');
  var chips = {};
  TIERS.forEach(function (t) {
    chips[t] = document.querySelector('.tier-chip[data-tier="' + t + '"]');
  });

  function activeTiers() {
    var active = {};
    TIERS.forEach(function (t) { active[t] = body.classList.contains('show-' + t); });
    return active;
  }

  function updateCounts() {
    var active = activeTiers();
    var grandTotal = 0;
    document.querySelectorAll('section.dategroup[data-national]').forEach(function (sec) {
      var visible = 0;
      TIERS.forEach(function (t) {
        if (active[t]) visible += parseInt(sec.getAttribute('data-' + t), 10) || 0;
      });
      grandTotal += visible;
      var countEl = sec.querySelector('.date-count');
      if (countEl) countEl.textContent = visible + '件';
      var pill = document.querySelector('.pill[href="#' + sec.id + '"] .pill-count');
      if (pill) pill.textContent = visible;
    });
    if (totalEl) totalEl.textContent = grandTotal;
  }

  function apply(tier, on) {
    body.classList.toggle('show-' + tier, on);
    if (chips[tier]) chips[tier].setAttribute('aria-pressed', on ? 'true' : 'false');
  }

  function applyAll(state) {
    TIERS.forEach(function (t) { apply(t, !!state[t]); });
    updateCounts();
    try { localStorage.setItem('editorial-digest-tiers', JSON.stringify(state)); } catch (e) {}
  }

  var initial = DEFAULT_ON;
  try {
    var saved = localStorage.getItem('editorial-digest-tiers');
    if (saved) initial = JSON.parse(saved);
  } catch (e) {}
  applyAll(initial);

  TIERS.forEach(function (t) {
    if (!chips[t]) return;
    chips[t].addEventListener('click', function () {
      var state = activeTiers();
      state[t] = !state[t];
      applyAll(state);
    });
  });
})();
"""


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def render_html(results: list, run_date: date) -> str:
    """SourceResult のリストから週間ダイジェストHTMLを組み立てる。

    results の各要素は main.py の SourceResult 互換（name / category / tier /
    items / error / skipped_by_robots 属性を持つ）であればよい。items の各
    要素も同様に title / link / published 属性を持つ Item 互換オブジェクト。
    main.py 側で既に直近7日間へフィルタ済みである前提（ここでは日付ごとの
    グルーピングのみ行い、再フィルタはしない）。tier は national / block /
    regional の3種類（未知の値は regional 扱い）。
    """
    def norm_tier(t: str) -> str:
        return t if t in TIERS else "regional"

    items_flat = []
    for r in results:
        tier = norm_tier(r.tier)
        for it in r.items:
            d = parse_published_date(it.published, run_date) or run_date
            t = parse_published_time(it.published)
            items_flat.append({
                "name": r.name, "tier": tier, "title": it.title,
                "link": it.link, "published": it.published, "date": d, "time": t,
                "paid": getattr(it, "paid", False),
            })

    by_date: dict[date, list[dict]] = defaultdict(list)
    for x in items_flat:
        by_date[x["date"]].append(x)

    if by_date:
        max_date = max(by_date)
        min_date = min(by_date)
    else:
        max_date = min_date = run_date

    for items in by_date.values():
        items.sort(key=lambda x: (x["time"] is None, x["time"] or "", x["name"]))

    sorted_dates = sorted(by_date.keys(), reverse=True)

    tag_class = {"national": "src-tag", "block": "src-tag src-tag-block", "regional": "src-tag src-tag-regional"}

    nav_pills = []
    sections = []
    for d in sorted_dates:
        items = by_date[d]
        tier_counts = {t: sum(1 for it in items if it["tier"] == t) for t in TIERS}
        default_count = tier_counts["national"]
        anchor = f"d-{d.isoformat()}"
        nav_pills.append(
            f'<a class="pill" href="#{anchor}">{d.month}/{d.day}'
            f'<span class="pill-count">{default_count}</span></a>'
        )

        rows = []
        for it in items:
            tier = it["tier"]
            title = _esc(it["title"])
            link = _esc(it["link"])
            src = _esc(it["name"])
            time_html = f'<time>{it["time"]}</time>' if it["time"] else ""
            paid_html = '<span class="paid-badge">会員限定</span>' if it["paid"] else ""
            rows.append(
                f'<li class="article-item tier-{tier}"><a class="article" href="{link}" target="_blank" rel="noopener noreferrer">'
                f'<span class="article-main"><span class="{tag_class[tier]}">{src}</span>'
                f'<span class="article-title">{title}{paid_html}</span></span>{time_html}</a></li>'
            )

        wd = WEEKDAY_JP[d.weekday()]
        latest_flag = ' <span class="latest-flag">最新</span>' if d == max_date else ""
        data_attrs = " ".join(f'data-{t}="{tier_counts[t]}"' for t in TIERS)
        sections.append(f'''
<section class="dategroup" id="{anchor}" {data_attrs}>
  <div class="date-head">
    <h2>{d.month}<span class="slash">/</span>{d.day}<span class="wd">（{wd}）</span></h2>
    <span class="date-count">{default_count}件</span>{latest_flag}
  </div>
  <ul class="article-list">{"".join(rows)}</ul>
</section>''')

    special_by_tier: dict[str, list[str]] = {t: [] for t in TIERS}
    for r in results:
        reason = getattr(r, "unavailable_reason", None)
        if r.skipped_by_robots:
            reason = reason or "サイト運営者の意向により、このページでは取得していません。"
            note = f'<p class="note note-skip"><strong>{_esc(r.name)}</strong>：{_esc(reason)}</p>'
        elif r.error or not r.items:
            reason = reason or "現在、記事を取得できませんでした（サイト側の変更や一時的な不具合の可能性があります）。"
            note = f'<p class="note note-error"><strong>{_esc(r.name)}</strong>：{_esc(reason)}</p>'
        else:
            continue
        special_by_tier[norm_tier(r.tier)].append(note)

    special_sections = ""
    for t in TIERS:
        notes = special_by_tier[t]
        if not notes:
            continue
        special_sections += (
            f'<section class="dategroup special special-{t}">'
            f'<div class="date-head"><h2 class="special-h">取得できなかった新聞社（{TIER_LABEL[t]}）</h2></div>'
            + "".join(notes) + "</section>"
        )

    tier_names = {t: [r.name for r in results if norm_tier(r.tier) == t] for t in TIERS}
    tier_totals = {t: sum(1 for x in items_flat if x["tier"] == t) for t in TIERS}
    range_label = f"{min_date.month}/{min_date.day} 〜 {max_date.month}/{max_date.day}"

    chips_html = "".join(
        f'<button type="button" class="tier-chip" data-tier="{t}" aria-pressed="{"true" if t == "national" else "false"}">'
        f'{TIER_LABEL[t]}<span class="tier-chip-count">{len(tier_names[t])}紙</span></button>'
        for t in TIERS
    )

    return f'''<title>社説まとめ 週間ダイジェスト</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>{_CSS}</style>

<div class="wrap">
  <header class="masthead">
    <p class="eyebrow">EDITORIAL DIGEST · WEEKLY</p>
    <h1>社説まとめ<br>週間ダイジェスト</h1>
    <p class="summary">{range_label}（過去1週間）・表示中 <strong id="total-count">{tier_totals["national"]}</strong>件</p>
    <p class="disclaimer">タイトル・リンク・日付のみを収集しています。本文は各紙サイトでお読みください。</p>
    <div class="scope-toggle">
      <span class="scope-label">表示する範囲</span>
      <div class="tier-chips">
{chips_html}
      </div>
    </div>
  </header>

  <nav class="quicknav" aria-label="日付へジャンプ">
    <div class="pill-row">
{"".join(nav_pills)}
    </div>
  </nav>

  <main>
{"".join(sections)}
{special_sections}
  </main>

  <footer>
    <p>社説まとめツールが自動生成 / 基準日: {run_date.isoformat()}。各リンクは記事本文へ遷移します。</p>
    <p>「会員限定」表示は参考情報です。表示が無くても無料と保証するものではありません。</p>
  </footer>
</div>

<script>{_SCRIPT_TEMPLATE}</script>
'''
