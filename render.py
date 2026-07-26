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
from dataclasses import dataclass
from datetime import date, datetime

from pubdate import parse_published_date, parse_published_time

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]
TIERS = ["national", "block", "regional"]
TIER_LABEL = {"national": "全国紙", "block": "ブロック紙", "regional": "地方紙"}
CONTACT_EMAIL = "t.iizuka188@gmail.com"

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
.masthead-top { display: flex; align-items: center; justify-content: space-between; gap: 0.75rem; margin: 0 0 0.5rem; }
.eyebrow { font-size: 0.72rem; letter-spacing: 0.14em; color: var(--ink-faint); text-transform: uppercase; margin: 0; }
.updated-at { margin: 0; flex: none; font-size: 0.72rem; color: var(--ink-faint); font-variant-numeric: tabular-nums; }
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
button.tier-chip:hover { background: var(--accent-soft); }
button.tier-chip[aria-pressed="true"] { background: var(--accent); color: var(--surface); }
button.tier-chip:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }

button.paid-toggle {
  margin-top: 0.6rem; width: 100%; font: inherit; font-size: 0.78rem; font-weight: 600;
  padding: 0.45rem 0.7rem; border-radius: 8px; border: 1px solid var(--rule);
  background: transparent; color: var(--ink-muted); cursor: pointer;
}
button.paid-toggle:hover { background: var(--warn-soft); }
button.paid-toggle[aria-pressed="true"] { background: var(--warn-soft); color: var(--warn); border-color: var(--warn); }
button.paid-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
body.hide-paid li.paid-item { display: none; }

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
ul.article-list { list-style:none; margin:0.6rem 0 0; padding:0; }
ul.article-list li { border-top:1px solid var(--rule); }
ul.article-list li:first-child { border-top:none; }
body:not(.show-national) li.tier-national { display: none; }
body:not(.show-block) li.tier-block { display: none; }
body:not(.show-regional) li.tier-regional { display: none; }

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


.empty-today { color: var(--ink-faint); font-size: 0.88rem; padding: 1.5rem 0.15rem; }

footer { padding:1.75rem 1.25rem 0; color:var(--ink-faint); font-size:0.78rem; line-height:1.7; }
footer a { color: var(--accent); }
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
    var grandTotal = 0;
    document.querySelectorAll('section.dategroup').forEach(function (sec) {
      var count = 0;
      sec.querySelectorAll('li.article-item').forEach(function (li) {
        if (li.offsetParent !== null) count++;
      });
      grandTotal += count;
      var countEl = sec.querySelector('.date-count');
      if (countEl) countEl.textContent = count + '件';
      var pill = document.querySelector('.pill[href="#' + sec.id + '"] .pill-count');
      if (pill) pill.textContent = count;
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

  var paidToggle = document.getElementById('paid-toggle');
  var hidePaid = false;
  function applyPaidToggle() {
    body.classList.toggle('hide-paid', hidePaid);
    if (paidToggle) {
      paidToggle.setAttribute('aria-pressed', hidePaid ? 'true' : 'false');
      paidToggle.textContent = hidePaid ? '会員限定記事: 非表示中' : '会員限定記事: 表示中';
    }
    updateCounts();
    try { localStorage.setItem('editorial-digest-hide-paid', hidePaid ? '1' : '0'); } catch (e) {}
  }
  try {
    hidePaid = localStorage.getItem('editorial-digest-hide-paid') === '1';
  } catch (e) {}
  applyPaidToggle();
  if (paidToggle) {
    paidToggle.addEventListener('click', function () {
      hidePaid = !hidePaid;
      applyPaidToggle();
    });
  }
})();
"""


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


def _normalize_tier(tier: str) -> str:
    return tier if tier in TIERS else "regional"


@dataclass
class _FlatItem:
    name: str
    tier: str
    title: str
    link: str
    time: str | None
    date: date
    paid: bool


def _flatten_items(results: list, run_date: date) -> list[_FlatItem]:
    flat = []
    for r in results:
        tier = _normalize_tier(r.tier)
        for it in r.items:
            flat.append(_FlatItem(
                name=r.name, tier=tier, title=it.title, link=it.link,
                time=parse_published_time(it.published),
                date=parse_published_date(it.published, run_date) or run_date,
                paid=getattr(it, "paid", False),
            ))
    return flat


def _group_by_date(items_flat: list[_FlatItem]) -> dict[date, list[_FlatItem]]:
    by_date: dict[date, list[_FlatItem]] = defaultdict(list)
    for item in items_flat:
        by_date[item.date].append(item)
    for items in by_date.values():
        items.sort(key=lambda x: (x.time is None, x.time or "", x.name))
    return by_date


_TAG_CLASS = {"national": "src-tag", "block": "src-tag src-tag-block", "regional": "src-tag src-tag-regional"}


def _render_article_row(item: _FlatItem) -> str:
    title = _esc(item.title)
    link = _esc(item.link)
    src = _esc(item.name)
    time_html = f'<time>{item.time}</time>' if item.time else ""
    paid_html = '<span class="paid-badge">会員限定</span>' if item.paid else ""
    paid_class = " paid-item" if item.paid else ""
    return (
        f'<li class="article-item tier-{item.tier}{paid_class}"><a class="article" href="{link}" target="_blank" rel="noopener noreferrer">'
        f'<span class="article-main"><span class="{_TAG_CLASS[item.tier]}">{src}</span>'
        f'<span class="article-title">{title}{paid_html}</span></span>{time_html}</a></li>'
    )


def _render_date_section(d: date, items: list[_FlatItem], max_date: date) -> tuple[str, str]:
    """指定日のナビゲーションピルとセクションHTMLを組み立てて返す。

    件数は既定表示である全国紙分のみを数える（他tierを表示した際の実際の
    件数は、クライアント側のJS (updateCounts) が表示要素数から再計算する）。
    """
    anchor = f"d-{d.isoformat()}"
    default_count = sum(1 for it in items if it.tier == "national")
    pill = (
        f'<a class="pill" href="#{anchor}">{d.month}/{d.day}'
        f'<span class="pill-count">{default_count}</span></a>'
    )

    rows = "".join(_render_article_row(it) for it in items)
    wd = WEEKDAY_JP[d.weekday()]
    latest_flag = ' <span class="latest-flag">最新</span>' if d == max_date else ""
    section = f'''
<section class="dategroup" id="{anchor}">
  <div class="date-head">
    <h2>{d.month}<span class="slash">/</span>{d.day}<span class="wd">（{wd}）</span></h2>
    <span class="date-count">{default_count}件</span>{latest_flag}
  </div>
  <ul class="article-list">{rows}</ul>
</section>'''
    return pill, section


def render_html(results: list, run_date: date, generated_at: datetime | None = None) -> str:
    """SourceResult のリストから週間ダイジェストHTMLを組み立てる。

    results の各要素は main.py の SourceResult 互換（name / category / tier /
    items / error / skipped_by_robots 属性を持つ）であればよい。items の各
    要素も同様に title / link / published 属性を持つ Item 互換オブジェクト。
    main.py 側で既に直近7日間へフィルタ済みである前提（ここでは日付ごとの
    グルーピングのみ行い、再フィルタはしない）。tier は national / block /
    regional の3種類（未知の値は regional 扱い）。
    generated_at はページ生成時刻（JST想定）。省略時はヘッダーに時刻を表示しない。
    """
    items_flat = _flatten_items(results, run_date)
    by_date = _group_by_date(items_flat)

    if by_date:
        max_date = max(by_date)
        min_date = min(by_date)
    else:
        max_date = min_date = run_date

    nav_pills = []
    sections = []
    for d in sorted(by_date, reverse=True):
        pill, section = _render_date_section(d, by_date[d], max_date)
        nav_pills.append(pill)
        sections.append(section)

    unavailable_names = [
        r.name for r in results
        if r.skipped_by_robots or r.error or not r.items
    ]

    unavailable_footer = (
        f'<p>現在取得できていない新聞社：{_esc("・".join(unavailable_names))}（{len(unavailable_names)}紙）</p>'
        if unavailable_names else ""
    )

    national_total = sum(1 for x in items_flat if x.tier == "national")
    range_label = f"{min_date.month}/{min_date.day} 〜 {max_date.month}/{max_date.day}"

    updated_at_html = (
        f'<p class="updated-at">UPDATED {generated_at.month}/{generated_at.day} '
        f'{generated_at.hour:02d}:{generated_at.minute:02d}</p>'
        if generated_at is not None else ""
    )

    chips_html = "".join(
        f'<button type="button" class="tier-chip" data-tier="{t}" aria-pressed="{"true" if t == "national" else "false"}">'
        f'{TIER_LABEL[t]}</button>'
        for t in TIERS
    )

    return f'''<title>社説まとめ 週間ダイジェスト</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>{_CSS}</style>

<div class="wrap">
  <header class="masthead">
    <div class="masthead-top">
      <p class="eyebrow">EDITORIAL DIGEST · WEEKLY</p>
      {updated_at_html}
    </div>
    <h1>社説まとめ<br>週間ダイジェスト</h1>
    <p class="summary">{range_label}（過去1週間）・表示中 <strong id="total-count">{national_total}</strong>件</p>
    <p class="disclaimer">タイトル・リンク・日付のみ収集。本文は各紙サイトでご覧ください。</p>
    <div class="scope-toggle">
      <span class="scope-label">表示する範囲</span>
      <div class="tier-chips">
{chips_html}
      </div>
      <button type="button" class="paid-toggle" id="paid-toggle" aria-pressed="false">会員限定記事: 表示中</button>
    </div>
  </header>

  <nav class="quicknav" aria-label="日付へジャンプ">
    <div class="pill-row">
{"".join(nav_pills)}
    </div>
  </nav>

  <main>
{"".join(sections)}
  </main>

  <footer>
    <p>社説まとめツールが自動生成 / 基準日: {run_date.isoformat()}。個人利用目的の非公式リンク集で、著作権は各社に帰属します。</p>
    <p>内容の正確性は保証しません（記事削除等でリンク切れの場合あり）。「会員限定」表示も参考情報です。</p>
    {unavailable_footer}
    <p>ご連絡・削除のご依頼は <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a> まで。</p>
  </footer>
</div>

<script>{_SCRIPT_TEMPLATE}</script>
'''


def render_today_html(results: list, run_date: date, generated_at: datetime | None = None) -> str:
    """SourceResult のリストから run_date当日分のみのWebページ (output/today.html) を
    組み立てる。

    results の items は呼び出し側（main.py の run_today）で既に run_date
    当日分のみに絞り込み済みである前提。週間ダイジェスト（render_html）と
    異なり、ある紙が0件でも取得失敗とはみなさない（1日ごとに必ず社説が
    掲載されるとは限らないため）。
    """
    items_flat = _flatten_items(results, run_date)
    by_date = _group_by_date(items_flat)
    items_today = by_date.get(run_date, [])

    national_total = sum(1 for x in items_today if x.tier == "national")
    wd = WEEKDAY_JP[run_date.weekday()]
    date_label = f"{run_date.month}/{run_date.day}（{wd}）"

    updated_at_html = (
        f'<p class="updated-at">UPDATED {generated_at.month}/{generated_at.day} '
        f'{generated_at.hour:02d}:{generated_at.minute:02d}</p>'
        if generated_at is not None else ""
    )

    chips_html = "".join(
        f'<button type="button" class="tier-chip" data-tier="{t}" aria-pressed="{"true" if t == "national" else "false"}">'
        f'{TIER_LABEL[t]}</button>'
        for t in TIERS
    )

    rows = "".join(_render_article_row(it) for it in items_today)
    empty_html = (
        '<p class="empty-today">本日分の社説はまだ掲載されていません。発行が夜間・早朝の紙や、'
        '本日休載の紙がある場合があります。時間をおいて再取得してください。</p>'
        if not items_today else ""
    )
    section = f'''
<section class="dategroup" id="d-{run_date.isoformat()}">
  <ul class="article-list">{rows}</ul>
  {empty_html}
</section>'''

    return f'''<title>社説まとめ 当日版</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<style>{_CSS}</style>

<div class="wrap">
  <header class="masthead">
    <div class="masthead-top">
      <p class="eyebrow">EDITORIAL DIGEST · TODAY</p>
      {updated_at_html}
    </div>
    <h1>本日の社説<br>まとめ</h1>
    <p class="summary">{date_label}・表示中 <strong id="total-count">{national_total}</strong>件</p>
    <p class="disclaimer">タイトル・リンク・日付のみ収集。本文は各紙サイトでご覧ください。</p>
    <div class="scope-toggle">
      <span class="scope-label">表示する範囲</span>
      <div class="tier-chips">
{chips_html}
      </div>
      <button type="button" class="paid-toggle" id="paid-toggle" aria-pressed="false">会員限定記事: 表示中</button>
    </div>
  </header>

  <main>
{section}
  </main>

  <footer>
    <p>社説まとめツールが自動生成 / 基準日: {run_date.isoformat()}（当日分のみ）。個人利用目的の非公式リンク集で、著作権は各社に帰属します。</p>
    <p>内容の正確性は保証しません（記事削除等でリンク切れの場合あり）。「会員限定」表示も参考情報です。</p>
    <p>ご連絡・削除のご依頼は <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a> まで。</p>
  </footer>
</div>

<script>{_SCRIPT_TEMPLATE}</script>
'''
