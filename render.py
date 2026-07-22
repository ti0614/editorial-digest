"""main.py が取得した結果 (SourceResult のリスト) から、直近1週間分の
社説ダイジェストをまとめたモバイル向けWebページ (output/digest.html) を
生成するモジュール。

全国紙（tier: national）を既定表示、ブロック紙・地方紙（tier: regional）は
ページ内トグルで表示する構成。外部CDN・Webフォントは使わず自己完結。
"""
from __future__ import annotations

import html
from collections import defaultdict
from datetime import date

from pubdate import parse_published_date, parse_published_time

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]

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
  display: flex; align-items: center; justify-content: space-between; gap: 0.75rem;
  background: var(--surface); border: 1px solid var(--rule); border-radius: 10px;
  padding: 0.7rem 0.9rem;
}
.scope-toggle .scope-label { font-size: 0.85rem; line-height: 1.5; color: var(--ink-muted); }
.scope-toggle .scope-label b { color: var(--ink); font-weight: 600; }
button.scope-btn {
  flex: none; font: inherit; font-size: 0.82rem; font-weight: 600;
  padding: 0.5rem 0.85rem; border-radius: 8px; border: 1px solid var(--accent);
  background: transparent; color: var(--accent); cursor: pointer;
  white-space: nowrap;
}
button.scope-btn:hover { background: var(--accent-soft); }
button.scope-btn[aria-pressed="true"] { background: var(--accent); color: var(--surface); }
button.scope-btn:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

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
li.regional { display: none; }
body.show-regional li.regional { display: list-item; }

.regional-block { display: none; }
body.show-regional .regional-block { display: block; }

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
.src-tag-regional { color: var(--ink-muted); background: transparent; border: 1px solid var(--rule); }
.article-title { font-size:0.98rem; line-height:1.55; }
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
  var body = document.body;
  var btn = document.getElementById('regional-toggle');
  var label = document.querySelector('.scope-label');
  var totalEl = document.getElementById('total-count');
  var natLabel = %(nat_label)s;
  var natTotal = %(nat_total)d;
  var allTotal = %(all_total)d;

  function updateCounts(showRegional) {
    document.querySelectorAll('section.dategroup[data-nat]').forEach(function (sec) {
      var nat = parseInt(sec.getAttribute('data-nat'), 10);
      var total = parseInt(sec.getAttribute('data-total'), 10);
      var countEl = sec.querySelector('.date-count');
      if (countEl) countEl.textContent = (showRegional ? total : nat) + '件';
      var pill = document.querySelector('.pill[href="#' + sec.id + '"] .pill-count');
      if (pill) pill.textContent = showRegional ? total : nat;
    });
    if (totalEl) totalEl.textContent = showRegional ? allTotal : natTotal;
  }

  function apply(showRegional) {
    body.classList.toggle('show-regional', showRegional);
    btn.setAttribute('aria-pressed', showRegional ? 'true' : 'false');
    btn.textContent = showRegional ? '全国紙のみに戻す' : 'ブロック紙・地方紙も見る';
    label.innerHTML = showRegional
      ? '<b>全国紙＋ブロック紙・地方紙</b>を表示中'
      : '<b>全国紙</b>（' + natLabel + '）を表示中';
    updateCounts(showRegional);
    try { localStorage.setItem('editorial-digest-show-regional', showRegional ? '1' : '0'); } catch (e) {}
  }

  var initial = false;
  try { initial = localStorage.getItem('editorial-digest-show-regional') === '1'; } catch (e) {}
  apply(initial);

  btn.addEventListener('click', function () {
    apply(!body.classList.contains('show-regional'));
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
    グルーピングのみ行い、再フィルタはしない）。
    """
    items_flat = []
    for r in results:
        for it in r.items:
            d = parse_published_date(it.published, run_date) or run_date
            t = parse_published_time(it.published)
            items_flat.append({
                "name": r.name, "tier": r.tier, "title": it.title,
                "link": it.link, "published": it.published, "date": d, "time": t,
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

    nav_pills = []
    sections = []
    for d in sorted_dates:
        items = by_date[d]
        nat_count = sum(1 for it in items if it["tier"] == "national")
        total_count = len(items)
        anchor = f"d-{d.isoformat()}"
        nav_pills.append(
            f'<a class="pill" href="#{anchor}">{d.month}/{d.day}'
            f'<span class="pill-count">{nat_count}</span></a>'
        )

        rows = []
        for it in items:
            is_national = it["tier"] == "national"
            title = _esc(it["title"])
            link = _esc(it["link"])
            src = _esc(it["name"])
            time_html = f'<time>{it["time"]}</time>' if it["time"] else ""
            li_class = "article-item" if is_national else "article-item regional"
            tag_class = "src-tag" if is_national else "src-tag src-tag-regional"
            rows.append(
                f'<li class="{li_class}"><a class="article" href="{link}" target="_blank" rel="noopener noreferrer">'
                f'<span class="article-main"><span class="{tag_class}">{src}</span>'
                f'<span class="article-title">{title}</span></span>{time_html}</a></li>'
            )

        wd = WEEKDAY_JP[d.weekday()]
        latest_flag = ' <span class="latest-flag">最新</span>' if d == max_date else ""
        sections.append(f'''
<section class="dategroup" id="{anchor}" data-nat="{nat_count}" data-total="{total_count}">
  <div class="date-head">
    <h2>{d.month}<span class="slash">/</span>{d.day}<span class="wd">（{wd}）</span></h2>
    <span class="date-count">{nat_count}件</span>{latest_flag}
  </div>
  <ul class="article-list">{"".join(rows)}</ul>
</section>''')

    national_special, regional_special = [], []
    for r in results:
        if r.skipped_by_robots:
            note = f'<p class="note note-skip"><strong>{_esc(r.name)}</strong>：robots.txt の指定により取得を見送りました（意図した動作）。</p>'
        elif r.error:
            note = f'<p class="note note-error"><strong>{_esc(r.name)}</strong>：取得できませんでした（{_esc(r.error)}）。</p>'
        elif not r.items:
            note = f'<p class="note note-error"><strong>{_esc(r.name)}</strong>：現在のセレクタでは記事を取得できませんでした（要調査、sources.yaml を確認してください）。</p>'
        else:
            continue
        (national_special if r.tier == "national" else regional_special).append(note)

    special_sections = ""
    if national_special:
        special_sections += (
            '<section class="dategroup special"><div class="date-head">'
            '<h2 class="special-h">取得できなかった新聞社</h2></div>'
            + "".join(national_special) + "</section>"
        )
    if regional_special:
        special_sections += (
            '<section class="dategroup special regional-block" id="special-block">'
            '<div class="date-head"><h2 class="special-h">取得できなかった新聞社（ブロック紙・地方紙）</h2></div>'
            + "".join(regional_special) + "</section>"
        )

    national_names = [r.name for r in results if r.tier == "national"]
    total_national = sum(1 for x in items_flat if x["tier"] == "national")
    total_regional = sum(1 for x in items_flat if x["tier"] != "national")
    range_label = f"{min_date.month}/{min_date.day} 〜 {max_date.month}/{max_date.day}"

    script = _SCRIPT_TEMPLATE % {
        "nat_label": '"' + "・".join(national_names) + '"',
        "nat_total": total_national,
        "all_total": total_national + total_regional,
    }

    return f'''<title>社説まとめ 週間ダイジェスト</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>{_CSS}</style>

<div class="wrap">
  <header class="masthead">
    <p class="eyebrow">EDITORIAL DIGEST · WEEKLY</p>
    <h1>社説まとめ<br>週間ダイジェスト</h1>
    <p class="summary">{range_label}（過去1週間）・全国紙 <strong id="total-count">{total_national}</strong>件</p>
    <p class="disclaimer">タイトル・リンク・日付のみを収集しています。本文は各紙サイトでお読みください。</p>
    <div class="scope-toggle">
      <span class="scope-label"><b>全国紙</b>（{"・".join(national_names)}）を表示中</span>
      <button type="button" class="scope-btn" id="regional-toggle" aria-pressed="false">
        ブロック紙・地方紙も見る
      </button>
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
    <p>editorial-digest（社説まとめツール）の出力を元に生成 / 基準日: {run_date.isoformat()}。各リンクは記事本文へ遷移します。</p>
  </footer>
</div>

<script>{script}</script>
'''
