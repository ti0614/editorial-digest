"""main.py が取得した結果 (SourceResult のリスト) から、モバイル向けの
自己完結型Webページを生成するモジュール。`render_today_html()`が本日分のみの
ページ(output/today.html)、`render_archive_html()`がアーカイブ検索
(output/archive.html)を生成する。いずれも`_render_page()`が組み立てる共通の
ページ骨格（head/masthead/footer/script）を共有し、見出し・概要・ナビ・本文・
フッター文言など異なる部分だけを差し替える。

全国紙（tier: national）を既定表示、ブロック紙（tier: block）・地方紙
（tier: regional）はページ内のチップボタンでそれぞれ独立に表示切り替え
できる構成。外部CDN・Webフォントは使わず自己完結。
"""
from __future__ import annotations

import html
from collections import defaultdict
from dataclasses import dataclass
from datetime import date

from pubdate import parse_published_date, parse_published_time

WEEKDAY_JP = ["月", "火", "水", "木", "金", "土", "日"]
TIERS = ["national", "block", "regional"]
TIER_LABEL = {"national": "全国紙", "block": "ブロック紙", "regional": "地方紙"}
CONTACT_EMAIL = "t.iizuka188@gmail.com"
SITE_URL = "https://ti0614.github.io/editorial-digest/"

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
.crosslink { margin: 0; flex: none; font-size: 0.72rem; }
.crosslink a { color: var(--accent); text-decoration: none; font-weight: 600; }
.crosslink a:hover { text-decoration: underline; }
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
  width: 100%; font: inherit; font-size: 0.82rem; font-weight: 600;
  padding: 0.55rem 0.7rem; border-radius: 8px; border: 1px solid var(--rule);
  background: transparent; color: var(--ink-muted); cursor: pointer;
}
.scope-toggle button.paid-toggle { margin-top: 0.6rem; }
button.paid-toggle:hover { background: var(--warn-soft); }
button.paid-toggle[aria-pressed="true"] { background: var(--warn-soft); color: var(--warn); border-color: var(--warn); }
button.paid-toggle:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
body.hide-paid li.paid-item { display: none; }

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
.date-head h2 .yr { font-size: 0.95rem; color: var(--ink-faint); font-family: "Hiragino Sans","Yu Gothic",sans-serif; font-weight:400; margin-right: 0.2rem; }
.date-count { font-size:0.78rem; color:var(--ink-faint); font-variant-numeric: tabular-nums; }
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

.search-panel { background: var(--surface); border: 1px solid var(--rule); border-radius: 10px; padding: 0.9rem; }
.search-panel-label {
  display: flex; align-items: baseline; justify-content: space-between; gap: 0.5rem;
  font-size: 0.72rem; letter-spacing: 0.06em; color: var(--ink-faint); margin: 0 0 0.7rem;
}
.field-row { margin: 0 0 0.6rem; }
.field-row:last-child { margin-bottom: 0; }
.field-caption { display:block; font-size: 0.7rem; color: var(--ink-faint); margin: 0 0 0.3rem; }
.archive-date {
  width:100%; font: inherit; font-size:0.95rem; padding:0.6rem 0.75rem; border-radius:8px;
  border:1px solid var(--rule); background:var(--bg); color:var(--ink);
}
.archive-date:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
/* 入力欄そのものには枠を持たせず、チップと入力を束ねる箱に持たせる。
   inputの中に要素は置けないため、入力欄に見える箱を作って中に並べている。 */
.search-box {
  display:flex; flex-wrap:wrap; align-items:center; gap:0.3rem;
  padding:0.45rem 0.6rem; border-radius:8px; border:1px solid var(--rule);
  background:var(--bg); cursor:text;
}
.search-box:focus-within { outline:2px solid var(--accent); outline-offset:2px; }
.term-chips { display:contents; }
.archive-search {
  flex:1 1 5rem; min-width:5rem; font: inherit; font-size:0.95rem;
  padding:0.15rem 0.15rem; border:none; background:transparent; color:var(--ink);
}
.archive-search:focus { outline:none; }
.term-chip {
  display:inline-flex; align-items:center; gap:0.25rem; font-size:0.82rem;
  padding:0.1rem 0.2rem 0.1rem 0.5rem; border-radius:999px;
  background:var(--accent); color:var(--surface); white-space:nowrap;
}
button.term-remove {
  font: inherit; font-size:0.9em; line-height:1; padding:0 0.25rem; border:none;
  border-radius:999px; background:transparent; color:var(--surface); cursor:pointer;
}
button.term-remove:hover { background: rgba(255,255,255,0.25); }
button.term-remove:focus-visible { outline:2px solid var(--surface); outline-offset:1px; }
.suggest-row { display:flex; flex-wrap:wrap; align-items:center; gap:0.35rem; margin-top:0.5rem; }
.suggest-row[hidden] { display:none; }
.suggest-label { font-size:0.7rem; color:var(--ink-faint); }
button.suggest-chip {
  font: inherit; font-size:0.78rem; padding:0.15rem 0.55rem; border-radius:999px;
  border:1px solid var(--rule); background:transparent; color:var(--accent); cursor:pointer;
}
button.suggest-chip:hover { background: var(--accent-soft); }
button.suggest-chip:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
.period-selects { display:flex; gap:0.5rem; }
.period-selects select { flex:1 1 0; }
.period-selects select:disabled { color: var(--ink-faint); }
.archive-status { font-size:0.8rem; color:var(--ink-faint); margin:0.9rem 0 1rem; }

.active-filters {
  display: flex; flex-wrap: wrap; align-items: center; gap: 0.4rem;
  margin: 0.7rem 0 0; font-size: 0.82rem; color: var(--ink-muted); min-height: 1.6rem;
}
.filter-chip {
  display: inline-flex; align-items: center; gap: 0.3rem; padding: 0.22rem 0.6rem;
  border-radius: 999px; background: var(--accent-soft); color: var(--accent); font-weight: 600;
  font-size: 0.78rem; white-space: nowrap;
}
.filter-chip.is-exclude { background: var(--warn-soft); color: var(--warn); }
.filter-join { color: var(--ink-faint); font-size: 0.78rem; }
.filter-result-count { margin-left: auto; color: var(--ink-faint); font-variant-numeric: tabular-nums; font-size: 0.8rem; }
li.article-item.search-hide { display:none; }
button.load-more {
  display:block; width:100%; font:inherit; font-size:0.85rem; font-weight:600; padding:0.65rem;
  margin-top:1.5rem; border-radius:8px; border:1px solid var(--rule); background:transparent;
  color:var(--ink-muted); cursor:pointer;
}
button.load-more:hover { background: var(--accent-soft); color: var(--accent); }
button.load-more:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
button.load-more[hidden] { display:none; }

footer { padding:1.75rem 1.25rem 0; color:var(--ink-faint); font-size:0.78rem; line-height:1.7; }
footer a { color: var(--accent); }
html { scroll-behavior: smooth; }
@media (prefers-reduced-motion: reduce) { html { scroll-behavior: auto; } }
"""

# today.html・archive.html共通のtier切替・会員限定トグルのJSロジック
# （activeTiers/apply/applyAll・localStorage初期化・クリックハンドラ登録、
# 会員限定トグルの同等の一式）。呼び出し側のIIFE内で TIERS/DEFAULT_ON/body/
# chips/updateCounts が既に定義済みであることを前提に、その途中に埋め込む
# 断片であり、これ単体では完結しない。
_TIER_PAID_TOGGLE_JS = """
  function activeTiers() {
    var active = {};
    TIERS.forEach(function (t) { active[t] = body.classList.contains('show-' + t); });
    return active;
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

  var initialTiers = DEFAULT_ON;
  try {
    var savedTiers = localStorage.getItem('editorial-digest-tiers');
    if (savedTiers) initialTiers = JSON.parse(savedTiers);
  } catch (e) {}
  applyAll(initialTiers);

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
    });
    if (totalEl) totalEl.textContent = grandTotal;
  }
""" + _TIER_PAID_TOGGLE_JS + """
})();
"""

# アーカイブ検索ページ専用のスクリプト。他の2ページと違いサーバー側で記事を
# 埋め込まず、archive/index.json・archive/{YYYY-MM}.json をブラウザ側でfetchして
# 組み立てる。tier/会員限定トグルは_TIER_PAID_TOGGLE_JSを共有するが、
# 動的に追加されるセクションに対してupdateCountsを呼び直す必要があるため
# updateCounts自体は独自実装になっている。
_ARCHIVE_SCRIPT_TEMPLATE = r"""
(function () {
  var TIERS = ['national', 'block', 'regional'];
  var DEFAULT_ON = { national: true, block: false, regional: false };
  var TIER_LABEL = { national: '全国紙', block: 'ブロック紙', regional: '地方紙' };
  var WEEKDAY_JP = ['月', '火', '水', '木', '金', '土', '日'];
  // 取得の単位は月。「当月分だけ」にすると月初に1日分しか出ないため、常に
  // 新しい方から2ヶ月ぶん取る（月初でも28日分、月末でも62日分になる）。
  var MONTHS_PER_PAGE = 2;
  // 表示の単位は日。取得と切り離してあり、既定では新しい方から7日分だけ見せて
  // 「さらに過去分を表示」で7日ずつ伸ばす。読み逃しのキャッチアップ（旅行・
  // 連休で数日空けた分を読み返す）が遡って読む主な動機で、それ以上遡る調べもの
  // 用途は検索欄と日付絞り込みが担うため、既定は1週間で足りるという判断。
  var DISPLAY_DAYS = 7;

  var body = document.body;
  var totalEl = document.getElementById('total-count');
  var resultsEl = document.getElementById('archive-results');
  var searchInput = document.getElementById('archive-search');
  var yearSelect = document.getElementById('archive-year');
  var monthSelect = document.getElementById('archive-month');
  var suggestEl = document.getElementById('archive-suggest');
  var searchBox = document.getElementById('search-box');
  var termChipsEl = document.getElementById('term-chips');
  var loadMoreBtn = document.getElementById('load-more');
  var statusEl = document.getElementById('archive-status');
  var filtersEl = document.getElementById('active-filters');
  var chips = {};
  TIERS.forEach(function (t) { chips[t] = document.querySelector('.tier-chip[data-tier="' + t + '"]'); });

  var allMonths = [];       // 新しい順。取得とページ送りの単位。
  var allDates = [];        // 新しい順。「全◯日分」の表示と表示日数の窓に使う。
  var loadedMonths = 0;     // allMonthsの先頭から何ヶ月ぶん取得したか
  var shownDays = DISPLAY_DAYS;  // 新しい方から何日分を表示するか（取得済みの日数とは別）
  var fetchedMonths = {};   // 期間指定で先に取った月を二重取得しないための記録
  var terms = [];           // 確定した検索語（すべて対等にORで結ぶ）
  var periodYear = '';      // 期間絞り込みの年（''なら未指定）
  var periodMonth = '';     // 同・月（年が未指定なら無効）
  var searchAllActive = false;

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function pad(n) { n = parseInt(n, 10); return (n < 10 ? '0' : '') + n; }

  function extractTime(published) {
    if (!published) return null;
    var m = published.match(/(\d{1,2})時(\d{1,2})分/);
    if (m) return pad(m[1]) + ':' + pad(m[2]);
    m = published.match(/(\d{1,2}):(\d{2})(?!\d)/);
    if (m) return pad(m[1]) + ':' + m[2];
    return null;
  }

  function weekdayOf(dateStr) {
    // new Date(...).getDay()は実行環境のローカルタイムゾーンで解釈されるため、
    // JST以外のタイムゾーンで開くと曜日がずれる。タイムゾーンに依存しない
    // Date.UTC + getUTCDay()でY/M/Dの曜日だけを求める。
    var parts = dateStr.split('-').map(function (n) { return parseInt(n, 10); });
    var d = new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
    return WEEKDAY_JP[(d.getUTCDay() + 6) % 7];
  }

  function tierTagClass(tier) {
    if (tier === 'block') return 'src-tag src-tag-block';
    if (tier === 'regional') return 'src-tag src-tag-regional';
    return 'src-tag';
  }

  function flattenDateData(data) {
    var out = [];
    (data.sources || []).forEach(function (src) {
      var tier = TIERS.indexOf(src.tier) >= 0 ? src.tier : 'regional';
      (src.items || []).forEach(function (it) {
        out.push({
          name: src.name, tier: tier, title: it.title, link: it.link,
          time: extractTime(it.published), paid: !!it.paid,
        });
      });
    });
    return out;
  }

  function renderRow(it) {
    var timeHtml = it.time ? '<time>' + it.time + '</time>' : '';
    var paidHtml = it.paid ? '<span class="paid-badge">会員限定</span>' : '';
    var paidClass = it.paid ? ' paid-item' : '';
    return '<li class="article-item tier-' + it.tier + paidClass + '" data-title="' + esc(it.title.toLowerCase()) + '">' +
      '<a class="article" href="' + esc(it.link) + '" target="_blank" rel="noopener noreferrer">' +
      '<span class="article-main"><span class="' + tierTagClass(it.tier) + '">' + esc(it.name) + '</span>' +
      '<span class="article-title">' + esc(it.title) + paidHtml + '</span></span>' + timeHtml + '</a></li>';
  }

  function sortByTimeDesc(items) {
    // 新しい時刻順（降順）。時刻不明は新旧の判断が付かないため常に末尾に置く。
    return items.slice().sort(function (a, b) {
      if (!a.time && !b.time) return 0;
      if (!a.time) return 1;
      if (!b.time) return -1;
      if (a.time === b.time) return 0;
      return a.time > b.time ? -1 : 1;
    });
  }

  function renderSection(dateStr, items) {
    items = sortByTimeDesc(items);
    var section = document.createElement('section');
    section.className = 'dategroup';
    section.id = 'd-' + dateStr;
    var parts = dateStr.split('-');
    // アーカイブは複数年分をまたぐため、月日だけの見出しだと「7/28」等が
    // どの年か判別できない（実際に2026-07-28の1件だけの薄いデータが先頭に
    // 表示され、2025年のデータと誤認されたことがある）。年を省略せず表示する。
    section.innerHTML =
      '<div class="date-head"><h2><span class="yr">' + parts[0] + '</span><span class="slash">/</span>' + parseInt(parts[1], 10) + '<span class="slash">/</span>' + parseInt(parts[2], 10) +
      '<span class="wd">（' + weekdayOf(dateStr) + '）</span></h2>' +
      '<span class="date-count">' + items.length + '件</span></div>' +
      '<ul class="article-list">' + items.map(renderRow).join('') + '</ul>';
    return section;
  }

  function applySearchFilter() {
    // 「さらに過去分を表示」や日付ジャンプで後から追加される記事にも
    // 現在の検索クエリを適用する必要があるため、search-hideの付与は
    // searchInputのinputイベントではなくここで毎回全件に対して行う
    // （updateCountsはコンテンツ追加のたびに呼ばれるため、ここに置けば
    // 新規追加分にも自動的に反映される）。
    if (!searchInput) return;
    var terms = searchTerms();
    resultsEl.querySelectorAll('li.article-item').forEach(function (li) {
      var title = li.getAttribute('data-title');
      var match = !terms.length || terms.some(function (t) { return title.indexOf(t) !== -1; });
      li.classList.toggle('search-hide', !match);
    });
  }

  // 入力した語と、提案チップで足した語。OR（どれかを含めばヒット）で扱う。
  // 「高市」で検索しても、名前を出さず「首相」とだけ書いた社説は引っかからない。
  // どちらが旬の話題かを機械が判断できない以上、無関係な記事（別の国の首相等）が
  // 混ざるとしても候補を広く出す —— 静かに取りこぼす方が、過剰に含めるより悪い
  // という日付解釈と同じ方針。何を足したかは要約バーに出して取り消せるようにする。
  function pendingTerm() {
    return searchInput ? searchInput.value.trim().toLowerCase() : '';
  }

  // 確定した語＋入力中の語。入力中の語も即座に効かせる（Enterを押すまで
  // 結果が変わらないと、この画面の逐次絞り込みの操作感から外れるため）。
  function searchTerms() {
    var q = pendingTerm();
    return q ? terms.concat([q]) : terms.slice();
  }

  // 検索語以外の条件（tier・会員限定）を通るか。提案チップの件数も同じ条件で
  // 数えるため、isVisibleから切り出して共有する。
  function passesTierPaid(li) {
    if (hidePaid && li.classList.contains('paid-item')) return false;
    for (var i = 0; i < TIERS.length; i++) {
      if (li.classList.contains('tier-' + TIERS[i])) {
        return body.classList.contains('show-' + TIERS[i]);
      }
    }
    return true;
  }

  function isVisible(li) {
    // 記事の表示/非表示はCSSの4規則（search-hide・tier別・会員限定）だけで
    // 決まるため、クラスから直接判定する。以前はoffsetParentで実測していたが、
    // 全期間検索（Issue #57）で約1000日分・約2万件がDOMに載るようになり、
    // 1件ごとの強制レイアウトが1打鍵ごとに効くようになった（実測で約44ms、
    // クラス判定なら約6ms）ため、レイアウトを起こさない判定に置き換えた。
    if (li.classList.contains('search-hide')) return false;
    return passesTierPaid(li);
  }

  function updateCounts() {
    applySearchFilter();
    applyScope();
    var grandTotal = 0;
    resultsEl.querySelectorAll('section.dategroup').forEach(function (sec) {
      // 表示範囲の外のセクションは、hidden状態を保ったまま完全にスキップする
      // （件数にも数えない）。
      if (sec.classList.contains('out-of-scope')) { return; }
      var count = 0;
      sec.querySelectorAll('li.article-item').forEach(function (li) {
        if (isVisible(li)) count++;
      });
      grandTotal += count;
      var countEl = sec.querySelector('.date-count');
      if (countEl) countEl.textContent = count + '件';
      sec.hidden = count === 0;
    });
    if (totalEl) totalEl.textContent = grandTotal;
    renderActiveFilters(grandTotal);
    // 提案チップの件数もtier・会員限定・期間の影響を受けるため、ここで一緒に
    // 描き直す。個別のハンドラに任せると、tierを切り替えたときだけ件数が
    // 古いまま残る、といった取りこぼしが出る。
    renderSuggestions();
  }

  function renderActiveFilters(total) {
    // 上部の検索条件パネルと同じ並び順（タイトル→日付→表示する範囲→会員限定）で
    // アクティブな条件を＋でつないだ要約を表示し、AND条件で絞り込めることを
    // 可視化する。全国紙のみを「既定表示」として特別扱いせず、ブロック紙のみ・
    // 地方紙のみと同様に選択中のtierは常にそのまま示す（0個選択時は「選択なし」）。
    if (!filtersEl) return;
    var chipsHtml = [];
    var allTerms = searchTerms();
    if (allTerms.length) {
      // 確定した語（チップ）＋入力中の語はORなので「または」でつなぐ。＋（AND）と混同させない。
      chipsHtml.push('<span class="filter-chip">タイトル「' + esc(allTerms.join('」または「')) + '」</span>');
    }
    if (periodYear) {
      chipsHtml.push('<span class="filter-chip">' + periodLabel() + '</span>');
    }
    var selectedTiers = TIERS.filter(function (t) { return body.classList.contains('show-' + t); });
    if (selectedTiers.length === 0) {
      chipsHtml.push('<span class="filter-chip is-exclude">表示範囲: 選択なし</span>');
    } else {
      chipsHtml.push('<span class="filter-chip">' + selectedTiers.map(function (t) { return TIER_LABEL[t]; }).join('・') + '</span>');
    }
    if (hidePaid) {
      chipsHtml.push('<span class="filter-chip is-exclude">会員限定を除く</span>');
    }
    filtersEl.innerHTML = chipsHtml.join('<span class="filter-join">＋</span>') +
      '<span class="filter-result-count">' + total + '件</span>';
  }
""" + _TIER_PAID_TOGGLE_JS + r"""
  // ステータス行と「さらに過去分を表示」の出し分けはここに集約する。読み込みは
  // 月単位、表示は日単位、検索は全期間と粒度が3つあるため、各所で個別に文言を
  // 書き換えると噛み合わなくなる。
  function updateStatus() {
    if (!allDates.length) {
      statusEl.textContent = 'まだアーカイブがありません。';
      loadMoreBtn.hidden = true;
      return;
    }
    loadMoreBtn.hidden = true;
    if (periodYear) {
      statusEl.textContent = periodLabel() + 'のみ表示中';
      return;
    }
    if (searchTerms().length) {
      // 検索は読み込み済みの記事にしか掛からないため、全期間が揃ったかどうかを示す。
      statusEl.textContent = loadedMonths >= allMonths.length
        ? '全期間（' + allDates.length + '日分）から検索中'
        : '全期間を読み込み中… ' + loadedMonths + '/' + allMonths.length + 'ヶ月分';
      return;
    }
    var shown = shownDayCount();
    statusEl.textContent = shown >= allDates.length ? 'すべて表示中' : shown + '日分を表示中';
    loadMoreBtn.hidden = shown >= allDates.length;
  }

  function shownDayCount() {
    return Math.min(shownDays, allDates.length);
  }

  function periodLabel() {
    if (!periodYear) { return ''; }
    return periodYear + '年' + (periodMonth ? parseInt(periodMonth, 10) + '月' : '');
  }

  function periodPrefix() {
    if (!periodYear) { return ''; }
    return periodMonth ? periodYear + '-' + periodMonth : periodYear;
  }

  function inScope(dateStr) {
    // 表示範囲の決まり方。上から順に強い。
    //   1. 期間指定（年・年月）—— 検索と併用でき、「2020年の記事を検索」になる
    //   2. 検索中は全期間（Issue #57。窓を掛けると過去のヒットが消えるため）
    //   3. 既定は新しい方から DISPLAY_DAYS 日分の窓
    var prefix = periodPrefix();
    if (prefix) { return dateStr.indexOf(prefix) === 0; }
    // 確定済みチップ（terms）だけの状態でも「検索中」に含める。入力欄の文字
    // だけで判定すると、Enterで確定して入力欄を空にした途端に「検索していない」
    // 扱いになり、既定の直近7日分の窓が復活して結果が消えてしまう。
    if (searchTerms().length) { return true; }
    var limit = allDates.length ? allDates[shownDayCount() - 1] : null;
    return !limit || dateStr >= limit;
  }

  function applyScope() {
    resultsEl.querySelectorAll('section.dategroup').forEach(function (sec) {
      var out = !inScope(sec.id.slice(2));
      sec.classList.toggle('out-of-scope', out);
      if (out) { sec.hidden = true; }
    });
  }

  function fetchMonth(month) {
    if (fetchedMonths[month]) { return Promise.resolve(null); }
    return fetch('archive/' + month + '.json')
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  function insertSection(dateStr, section) {
    // 画面は日付の新しい順。通常は末尾追加で足りるが、期間指定で先に
    // 取得した月が混ざると順序が崩れるため、崩れる場合だけ位置を探して挿す。
    var last = resultsEl.lastElementChild;
    if (!last || last.id.slice(2) > dateStr) { resultsEl.appendChild(section); return; }
    var secs = resultsEl.children;
    for (var i = 0; i < secs.length; i++) {
      if (secs[i].id.slice(2) < dateStr) { resultsEl.insertBefore(section, secs[i]); return; }
    }
    resultsEl.appendChild(section);
  }

  function renderMonth(data) {
    if (!data) { return; }
    fetchedMonths[data.month] = true;
    // 月別ファイルのdaysは日付の昇順で入っているため、新しい順に積むよう逆順で回す。
    (data.days || []).slice().reverse().forEach(function (day) {
      if (document.getElementById('d-' + day.date)) { return; }
      insertSection(day.date, renderSection(day.date, flattenDateData(day)));
    });
  }

  function loadNextPage(onDone) {
    var batch = allMonths.slice(loadedMonths, loadedMonths + MONTHS_PER_PAGE);
    if (batch.length === 0) { if (onDone) onDone(); return; }
    Promise.all(batch.map(fetchMonth)).then(function (results) {
      results.forEach(renderMonth);
      loadedMonths += batch.length;
      updateCounts();
      updateStatus();
      if (onDone) onDone();
    });
  }

  // 指定した月をまとめて取得する（期間絞り込み用）。loadNextPageが新しい月から
  // 順に辿るのに対し、こちらは選ばれた年・月だけを名指しで取りに行く。
  function loadMonths(months, onDone) {
    var pending = months.filter(function (m) { return !fetchedMonths[m]; });
    if (!pending.length) { if (onDone) onDone(); return; }
    statusEl.textContent = '読み込み中…';
    loadMoreBtn.hidden = true;
    Promise.all(pending.map(fetchMonth)).then(function (results) {
      results.forEach(renderMonth);
      if (onDone) onDone();
    });
  }

  // 表示日数の窓を広げるのに必要な月がまだ読めていなければ取得する。先読みが
  // 効いていれば常に読み込み済みなので、実際に走るのは先読みを見送った場合だけ。
  function ensureMonthsForWindow(onDone) {
    var oldest = allDates[shownDayCount() - 1];
    var needed = allMonths.indexOf(oldest.slice(0, 7)) + 1;
    if (needed <= loadedMonths || loadedMonths >= allMonths.length) {
      if (onDone) onDone();
      return;
    }
    statusEl.textContent = '読み込み中…';
    loadNextPage(function () { ensureMonthsForWindow(onDone); });
  }

  function showMoreDays() {
    shownDays += DISPLAY_DAYS;
    ensureMonthsForWindow(function () { updateCounts(); updateStatus(); });
  }

  // タイトル検索は読み込み済みの記事にしか掛からないため、残りの月を取得して
  // おかないと、過去に一致する記事があっても「0件」に見えてしまう（Issue #57）。
  // 取得済みの月はDOMに残るので、この全期間読み込みは1回のページ表示につき
  // 一度きりで済む。表示日数の窓とは独立で、ここで取得しても既定の表示は
  // DISPLAY_DAYS日分のままにする。
  function ensureAllDatesLoaded() {
    if (searchAllActive || loadedMonths >= allMonths.length) { return; }
    searchAllActive = true;
    (function step() {
      if (loadedMonths >= allMonths.length) {
        searchAllActive = false;
        updateCounts();
        updateStatus();
        buildGramIndex();
        return;
      }
      loadNextPage(step);
    })();
  }

  // 初回表示を描いた直後に、残りの月を裏で取得しておく（Issue #66）。初回描画
  // より後に走るので最初に見える画面の速さは変わらず、そのうえで検索時の待ちが
  // 無くなる。ただし通信量は全期間ぶんに増えるため、データセーバー有効時と
  // 極端に遅い回線では見送り、従来どおり検索語が入ってから取得する。
  function prefetchAllMonths() {
    var conn = navigator.connection;
    if (conn && (conn.saveData || conn.effectiveType === '2g' || conn.effectiveType === 'slow-2g')) {
      return;
    }
    ensureAllDatesLoaded();
  }

  // ---- 関連語の提案 ----
  // 検索語を含むタイトルの中に不釣り合いに多く同居している語を出す。社説は
  // 人名を出さず「首相」「政権」とだけ書くことが多く、人名で検索すると当人を
  // 論じた社説の多くが漏れる。別名表を持つと政治的事実を手で書いて維持する
  // ことになるため、代わりに「こういう語でも探せる」と示すだけに留める。
  // 語の切り出しは形態素解析器を使わず、漢字の連なりの2〜4文字n-gramと
  // カタカナ語（丸ごと1語）で代用する。語の境界を知らないので「再稼」の
  // ような途中で切れた断片が混じるが、提案なので実害は小さいと判断した。
  var GRAM_KANJI = /[一-鿿]{2,}/g;
  var GRAM_KATA = /[゠-ヿー]{2,}/g;
  var GRAM_STOP = { '社説': 1, '主張': 1, '論説': 1, '日報': 1, '新聞': 1 };
  var GRAM_CHUNK = 2000;
  var gramIndex = null;     // gram -> 全タイトル中の出現件数
  var gramItems = null;     // 索引を作った時点の記事（タイトルと絞り込みに使う属性）
  var gramBuilding = false;

  function gramsOf(text, out) {
    var m;
    GRAM_KATA.lastIndex = 0;
    while ((m = GRAM_KATA.exec(text))) { if (!GRAM_STOP[m[0]]) { out[m[0]] = 1; } }
    GRAM_KANJI.lastIndex = 0;
    while ((m = GRAM_KANJI.exec(text))) {
      var run = m[0];
      for (var n = 2; n <= 4; n++) {
        for (var i = 0; i + n <= run.length; i++) {
          var g = run.substr(i, n);
          if (!GRAM_STOP[g]) { out[g] = 1; }
        }
      }
    }
    return out;
  }

  // 索引の構築は約2万件を1周するため、低速端末では2秒以上かかる。まとめて
  // 回すと画面が固まるので、GRAM_CHUNK件ずつ処理して制御を返す。全期間が
  // 揃ってから作る（途中で作ると読み込み済みの分だけの偏った統計になる）。
  function buildGramIndex() {
    if (gramIndex || gramBuilding || loadedMonths < allMonths.length) { return; }
    gramBuilding = true;
    // 提案チップの件数も同じ配列から数える。DOMを1件ずつ読むと約2万件の
    // getAttributeで打鍵ごとに数百msかかるため、属性もここで写し取っておく。
    gramItems = [];
    resultsEl.querySelectorAll('section.dategroup').forEach(function (sec) {
      var date = sec.id.slice(2);
      sec.querySelectorAll('li.article-item').forEach(function (li) {
        var tier = 'regional';
        for (var i = 0; i < TIERS.length; i++) {
          if (li.classList.contains('tier-' + TIERS[i])) { tier = TIERS[i]; break; }
        }
        gramItems.push({
          t: li.getAttribute('data-title'), d: date, tier: tier,
          paid: li.classList.contains('paid-item'),
        });
      });
    });
    var index = new Map();
    var pos = 0;
    (function step() {
      var end = Math.min(pos + GRAM_CHUNK, gramItems.length);
      for (; pos < end; pos++) {
        var set = gramsOf(gramItems[pos].t, Object.create(null));
        for (var g in set) { index.set(g, (index.get(g) || 0) + 1); }
      }
      if (pos < gramItems.length) { setTimeout(step, 0); return; }
      gramIndex = index;
      gramBuilding = false;
      renderSuggestions();
    })();
  }

  // qsは現在有効な検索語すべて（確定済みチップ＋入力中の語）。どれか1つでも
  // 含むタイトルをヒット集合とし（OR）、その中で全体に比べて不釣り合いに
  // 多く同居している語を選ぶ。選抜はリフト（出現率の比）で行う —— 単純な
  // 出現数で選ぶと「表明」「責任」「政治」のようなどの社説にも出る一般語が
  // 上位に来てしまうことを実データで確認済み。選んだ後の並びだけ出現数の
  // 多い順にする（数字を見て降順になっている方が直感的なため）。
  function suggestionsFor(qs) {
    if (!qs.length) { return []; }
    var hit = new Map();
    var n = 0;
    for (var i = 0; i < gramItems.length; i++) {
      var t = gramItems[i].t;
      var hitAny = false;
      var masked = t;
      for (var k = 0; k < qs.length; k++) {
        if (t.indexOf(qs[k]) >= 0) {
          hitAny = true;
          // 検索語の部分をマスクしてから切り出す。そうしないと隣接する文字を
          // 巻き込んだ断片（「高市」+「政権」→「市政権」）が上位に来る。
          masked = masked.split(qs[k]).join('　');
        }
      }
      if (!hitAny) { continue; }
      n++;
      var set = gramsOf(masked, Object.create(null));
      for (var g in set) { hit.set(g, (hit.get(g) || 0) + 1); }
    }
    if (n < 5) { return []; }
    var min = Math.max(3, n * 0.05);
    var total = gramItems.length;
    var scored = [];
    hit.forEach(function (c, g) {
      if (c < min) { return; }
      var overlaps = qs.some(function (q) { return g.indexOf(q) >= 0 || q.indexOf(g) >= 0; });
      if (overlaps) { return; }
      // ヒット集合内での出現率が全体での出現率より高いほど上に来る。
      scored.push([c * ((c / n) / (gramIndex.get(g) / total)), g]);
    });
    scored.sort(function (a, b) { return b[0] - a[0]; });
    var kept = [];
    for (var j = 0; j < scored.length && kept.length < 6; j++) {
      var g = maximalGram(scored[j][1], hit);
      var dup = kept.some(function (k) { return g.indexOf(k) >= 0 || k.indexOf(g) >= 0; });
      if (!dup) { kept.push(g); }
    }
    // 選抜はリフト順のまま、表示だけ出現数の多い順に並べ替える。
    kept.sort(function (a, b) { return (hit.get(b) || 0) - (hit.get(a) || 0); });
    return kept;
  }

  // n-gramは語の境界を知らないため「再稼働」から「再稼」、「内閣発足」から
  // 「閣発足」といった途中で切れた断片が出る。ある語を含むより長い語がほぼ
  // 同じ件数で存在するなら、短い方は長い方の一部を切り出しただけとみなして
  // 長い方に寄せる。辞書無しで断片をかなり減らせる。
  function maximalGram(gram, hit) {
    var base = hit.get(gram);
    var best = gram;
    hit.forEach(function (c, other) {
      if (other.length > best.length && other.indexOf(gram) >= 0 && c >= base * 0.8) {
        best = other;
      }
    });
    return best;
  }

  // 検索欄が空のとき、代わりに直近7日分で不釣り合いに多く出ている語を出す
  // （既定の表示日数DISPLAY_DAYSと単位を揃える）。「共起」ではなく「最近の
  // 頻度」を見る点が一緒に出てくる語の提案とは異なるが、仕組み（全体との
  // 出現率の比＝リフトで選び、maximalGramで断片を寄せる）は同じ。
  function trendingWords() {
    if (!gramIndex || !allDates.length) { return []; }
    var cutoff = allDates[Math.min(6, allDates.length - 1)];
    var hit = new Map();
    var n = 0;
    for (var i = 0; i < gramItems.length; i++) {
      if (gramItems[i].d < cutoff) { continue; }
      n++;
      var set = gramsOf(gramItems[i].t, Object.create(null));
      for (var g in set) { hit.set(g, (hit.get(g) || 0) + 1); }
    }
    if (n < 5) { return []; }
    var min = Math.max(3, n * 0.05);
    var total = gramItems.length;
    var scored = [];
    hit.forEach(function (c, g) {
      if (c < min) { return; }
      scored.push([c * ((c / n) / (gramIndex.get(g) / total)), g]);
    });
    scored.sort(function (a, b) { return b[0] - a[0]; });
    var kept = [];
    for (var j = 0; j < scored.length && kept.length < 6; j++) {
      var g = maximalGram(scored[j][1], hit);
      var dup = kept.some(function (k) { return g.indexOf(k) >= 0 || k.indexOf(g) >= 0; });
      if (!dup) { kept.push(g); }
    }
    kept.sort(function (a, b) { return (hit.get(b) || 0) - (hit.get(a) || 0); });
    return kept;
  }

  function renderChipButtons(label, words) {
    suggestEl.innerHTML = '<span class="suggest-label">' + label + '</span>' +
      words.map(function (w) {
        return '<button type="button" class="suggest-chip" data-word="' + esc(w) + '">' + esc(w) + '</button>';
      }).join('');
    suggestEl.hidden = false;
  }

  function renderSuggestions() {
    if (!suggestEl || !searchInput) { return; }
    var qs = searchTerms();
    if (!qs.length) {
      // 索引がまだ無い（データセーバー等で先読みを見送った、または構築中）
      // 場合は何も出さない。検索していないのに「集計中…」を出すと、何を
      // 待っているのか伝わらず不自然なため。
      var trend = gramIndex ? trendingWords() : [];
      if (!trend.length) { suggestEl.innerHTML = ''; suggestEl.hidden = true; return; }
      renderChipButtons('最近よく出ている語（押すと検索に使う）:', trend);
      return;
    }
    if (!gramIndex) {
      suggestEl.innerHTML = gramBuilding
        ? '<span class="suggest-label">関連する語を集計中…</span>' : '';
      suggestEl.hidden = !gramBuilding;
      return;
    }
    // 確定済みの語は自分のチップ（term-chip）を既に持っているので、提案の列には
    // 出さない。クリックすると確定側に移ってこの列から消える、という動きになる。
    var words = suggestionsFor(qs);
    if (!words.length) { suggestEl.innerHTML = ''; suggestEl.hidden = true; return; }
    // 件数は出さない。tier・会員限定・期間を通した後の件数を表示していたが、
    // その条件がぱっと見で分からず、何の数字か伝わらないという指摘があった。
    // 押せば要約バーの合計がすぐ更新されるので、気に入らなければ押し直せばよい。
    renderChipButtons('一緒に出てくる語（押すと検索に足す）:', words);
  }

  // 確定した検索語（打ってEnterした語・提案から押した語のどちらも同格）は
  // 入力欄の中にチップとして並べる。トークン入力の定番どおりチップを先、
  // 次に打ちかけの語を続ける並びにしている。
  function renderTermChips() {
    if (!termChipsEl) { return; }
    termChipsEl.innerHTML = terms.map(function (w) {
      return '<span class="term-chip">' + esc(w) +
        '<button type="button" class="term-remove" data-word="' + esc(w) +
        '" aria-label="' + esc(w) + 'を外す">×</button></span>';
    }).join('');
  }

  function addTerm(w) {
    w = w.trim().toLowerCase();
    if (w && terms.indexOf(w) < 0) { terms.push(w); }
  }

  function removeTerm(w) {
    var at = terms.indexOf(w);
    if (at >= 0) { terms.splice(at, 1); }
    afterTermsChanged();
  }

  function afterTermsChanged() {
    renderTermChips();
    updateCounts();
    updateStatus();
    if (searchTerms().length) {
      ensureAllDatesLoaded();
      buildGramIndex();
    }
  }

  if (termChipsEl) {
    termChipsEl.addEventListener('click', function (ev) {
      if (!ev.target.classList.contains('term-remove')) { return; }
      removeTerm(ev.target.getAttribute('data-word'));
      searchInput.focus();
    });
  }

  if (searchBox) {
    // 箱のどこを押しても入力に移る（見た目が入力欄なので、余白を押して
    // 反応しないと壊れて見える）。
    searchBox.addEventListener('mousedown', function (ev) {
      if (ev.target === searchBox || ev.target === termChipsEl) {
        ev.preventDefault();
        searchInput.focus();
      }
    });
  }

  if (searchInput) {
    // 入力中の語をチップとして確定する。Enterと、入力欄からフォーカスが
    // 外れた（blur）タイミングの両方から呼ぶ。スマホではEnterキーが押しにくい
    // 端末・IMEがあり、フォーカスを外す操作（他のチップやセレクトを触る、
    // 画面の別の場所をタップする）の方が確実に行えるため。
    function commitPending() {
      if (!searchInput.value.trim()) { return; }
      addTerm(searchInput.value);
      searchInput.value = '';
      afterTermsChanged();
    }

    searchInput.addEventListener('keydown', function (ev) {
      if (ev.key === 'Enter') {
        // 日本語入力の変換候補を確定するEnterもここに来る（isComposing:
        // true）。ここで拾うと変換途中の文字列がそのままチップになって
        // しまうため無視する。変換確定後、続けてEnterを押せば通常どおり
        // 確定できる。
        if (ev.isComposing) { return; }
        ev.preventDefault();
        commitPending();
        return;
      }
      // 入力が空のままBackspaceを押したら直前のチップを外す。トークン入力では
      // 期待される挙動で、無いと消し方が分からなくなる。
      if (ev.key === 'Backspace' && searchInput.value === '' && terms.length) {
        removeTerm(terms[terms.length - 1]);
      }
    });

    searchInput.addEventListener('blur', commitPending);
  }

  if (suggestEl) {
    suggestEl.addEventListener('click', function (ev) {
      // 件数のspanを押した場合もあるので、チップ本体まで辿る。語はtextContentに
      // 件数が混ざるためdata-wordから取る。
      var chip = ev.target.closest ? ev.target.closest('.suggest-chip') : null;
      if (!chip) { return; }
      addTerm(chip.getAttribute('data-word'));
      afterTermsChanged();
      searchInput.focus();
    });
  }

  if (loadMoreBtn) {
    loadMoreBtn.addEventListener('click', function () { showMoreDays(); });
  }

  if (searchInput) {
    var searchTimer = null;
    searchInput.addEventListener('input', function () {
      // 打ちかけの語も即座に効かせる（searchTerms()が拾う）。確定済みチップは
      // 打ち直しても消さない —— 打った語自体が対等なチップになった以上、
      // 「新しい語を打ち始めたら前のチップが消える」動きは驚きになるため。
      updateCounts();
      updateStatus();
      if (searchTimer) { clearTimeout(searchTimer); }
      if (!searchInput.value.trim()) { return; }
      // 1打鍵ごとに全期間読み込みや索引構築を起動しないよう、入力が落ち着いてから。
      searchTimer = setTimeout(function () {
        ensureAllDatesLoaded();
        buildGramIndex();
      }, 300);
    });
  }

  function applyPeriod() {
    var prefix = periodPrefix();
    var months = prefix
      ? allMonths.filter(function (m) { return m.indexOf(prefix) === 0; })
      : [];
    loadMonths(months, function () { updateCounts(); updateStatus(); });
  }

  function populateMonthOptions() {
    if (!monthSelect) { return; }
    // 年を選んでいないと月だけ指定しても意味が無いので選べなくする。データのある
    // 月だけを並べ、選んだのに0件という行き止まりを作らない。
    var months = periodYear
      ? allMonths.filter(function (m) { return m.slice(0, 4) === periodYear; })
          .map(function (m) { return m.slice(5); }).sort()
      : [];
    monthSelect.disabled = !periodYear;
    monthSelect.innerHTML = '<option value="">すべての月</option>' +
      months.map(function (m) { return '<option value="' + m + '">' + parseInt(m, 10) + '月</option>'; }).join('');
    if (months.indexOf(periodMonth) < 0) { periodMonth = ''; }
    monthSelect.value = periodMonth;
  }

  function populateYearOptions() {
    if (!yearSelect) { return; }
    var years = [];
    allMonths.forEach(function (m) {
      var y = m.slice(0, 4);
      if (years.indexOf(y) < 0) { years.push(y); }
    });
    yearSelect.innerHTML = '<option value="">すべての年</option>' +
      years.map(function (y) { return '<option value="' + y + '">' + y + '年</option>'; }).join('');
    populateMonthOptions();
  }

  if (yearSelect) {
    yearSelect.addEventListener('change', function () {
      periodYear = yearSelect.value;
      populateMonthOptions();
      applyPeriod();
    });
  }

  if (monthSelect) {
    monthSelect.addEventListener('change', function () {
      periodMonth = monthSelect.value;
      applyPeriod();
    });
  }

  fetch('archive/index.json').then(function (r) { return r.json(); }).then(function (data) {
    allDates = (data.dates || []).slice().sort().reverse();
    allMonths = (data.months || []).slice().sort().reverse();
    populateYearOptions();
    loadNextPage(prefetchAllMonths);
  }).catch(function () {
    statusEl.textContent = 'アーカイブの読み込みに失敗しました。時間をおいて再度お試しください。';
  });
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


def _time_sort_key(item: _FlatItem) -> tuple[bool, int, str]:
    """新しい時刻順（降順）で並べるためのキー。時刻不明は新旧の判断が
    付かないため常に末尾に置く。
    """
    if item.time is None:
        return (True, 0, item.name)
    h, m = item.time.split(":")
    return (False, -(int(h) * 60 + int(m)), item.name)


def _group_by_date(items_flat: list[_FlatItem]) -> dict[date, list[_FlatItem]]:
    by_date: dict[date, list[_FlatItem]] = defaultdict(list)
    for item in items_flat:
        by_date[item.date].append(item)
    for items in by_date.values():
        items.sort(key=_time_sort_key)
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


def _render_tier_chips() -> str:
    return "".join(
        f'<button type="button" class="tier-chip" data-tier="{t}" aria-pressed="{"true" if t == "national" else "false"}">'
        f'{TIER_LABEL[t]}</button>'
        for t in TIERS
    )


def _render_summary(label: str, total: int) -> str:
    return (
        f'    <p class="summary">{label}・表示中 <strong id="total-count">{total}</strong>件</p>\n'
        '    <p class="disclaimer">タイトル・リンク・日付のみ収集。本文は各紙サイトでご覧ください。</p>'
    )


def _render_footer(note: str = "", run_date: date | None = None) -> str:
    date_part = f" / 基準日: {run_date.isoformat()}{note}" if run_date else ""
    return (
        f'    <p>社説まとめツールが自動生成{date_part}。'
        '個人利用目的の非公式リンク集で、著作権は各社に帰属します。</p>\n'
        '    <p>内容の正確性は保証しません（記事削除等でリンク切れの場合あり）。「会員限定」表示も参考情報です。</p>\n'
        '    <p>一部の新聞社は、サイト側の意向により対象外としています。</p>\n'
        f'    <p>ご連絡・削除のご依頼は <a href="mailto:{CONTACT_EMAIL}">{CONTACT_EMAIL}</a> まで。</p>'
    )


def _render_crosslink(href: str, label: str) -> str:
    return f'<p class="crosslink"><a href="{href}">{label}</a></p>'


def _render_page(
    *, title: str, description: str, canonical_path: str, eyebrow: str, heading: str,
    crosslink_html: str, summary_html: str, main_html: str, footer_html: str,
    script: str = _SCRIPT_TEMPLATE, scope_toggle_html: str | None = None,
) -> str:
    """today.html・archive.htmlに共通のページ骨格（head/masthead/
    footer/script）を組み立てる。異なる部分（見出し・概要・本文・フッター
    文言）は呼び出し側が文字列として渡す。scriptは既定でtier/会員限定トグルの
    共通スクリプトだが、アーカイブページのように動的読み込みが絡むページは
    独自のスクリプトに差し替える。scope_toggle_htmlも既定はtier/会員限定トグルの
    共通ヘッダーブロックだが、アーカイブページはタイトル検索・日付絞り込みも
    含めた1つの検索パネルを渡す——today.htmlのtier/会員限定トグルと同様、
    ヘッダー内に置くことでheader.mastheadのborder-bottomが記事一覧の直前
    （main_htmlの先頭）に来るようにするため。
    """
    if scope_toggle_html is None:
        scope_toggle_html = (
            '    <div class="scope-toggle">\n'
            '      <span class="scope-label">表示する範囲</span>\n'
            '      <div class="tier-chips">\n'
            f'{_render_tier_chips()}\n'
            '      </div>\n'
            '      <button type="button" class="paid-toggle" id="paid-toggle" aria-pressed="false">会員限定記事: 表示中</button>\n'
            '    </div>'
        )
    canonical_url = f"{SITE_URL}{canonical_path}"
    desc_attr = _esc(description)
    title_attr = _esc(title)
    return f'''<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8" />
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="description" content="{desc_attr}" />
<link rel="canonical" href="{canonical_url}" />
<meta property="og:type" content="website" />
<meta property="og:locale" content="ja_JP" />
<meta property="og:title" content="{title_attr}" />
<meta property="og:description" content="{desc_attr}" />
<meta property="og:url" content="{canonical_url}" />
<meta name="twitter:card" content="summary" />
<meta name="twitter:title" content="{title_attr}" />
<meta name="twitter:description" content="{desc_attr}" />
<style>{_CSS}</style>
</head>
<body>
<div class="wrap">
  <header class="masthead">
    <div class="masthead-top">
      <p class="eyebrow">{eyebrow}</p>
      {crosslink_html}
    </div>
    <h1>{heading}</h1>
{summary_html}
{scope_toggle_html}
  </header>
  <main>
{main_html}
  </main>

  <footer>
{footer_html}
  </footer>
</div>

<script>{script}</script>
</body>
</html>
'''


def render_today_html(results: list, run_date: date) -> str:
    """SourceResult のリストから run_date当日分のみのWebページ (output/today.html) を
    組み立てる。

    results の items は呼び出し側（main.py の run_today）で既に run_date
    当日分のみに絞り込み済みである前提。ある紙が0件でも取得失敗とはみなさない
    （1日ごとに必ず社説が掲載されるとは限らないため）。
    """
    items_flat = _flatten_items(results, run_date)
    by_date = _group_by_date(items_flat)
    items_today = by_date.get(run_date, [])

    national_total = sum(1 for x in items_today if x.tier == "national")
    wd = WEEKDAY_JP[run_date.weekday()]
    date_label = f"{run_date.month}/{run_date.day}（{wd}）"

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

    summary_html = _render_summary(date_label, national_total)
    footer_html = _render_footer("（当日分のみ）", run_date)

    return _render_page(
        title="社説まとめ",
        description="全国紙・地方紙の社説（オピニオン）を毎日まとめる非公式リンク集。"
                     "本日分のタイトル・リンク・日付のみを掲載し、本文は各紙サイトでご覧いただけます。",
        canonical_path="",
        eyebrow="EDITORIAL DIGEST · TODAY",
        crosslink_html=_render_crosslink("archive.html", "アーカイブ検索へ"),
        heading="本日の社説<br>まとめ", summary_html=summary_html,
        main_html=section, footer_html=footer_html,
    )


def render_archive_html() -> str:
    """アーカイブ検索ページ (output/archive.html) を組み立てる。

    today.htmlと異なり、記事データはビルド時に埋め込まない。
    archive/index.json・archive/{YYYY-MM}.json（CIがコミットする日次スナップ
    ショットを月ごとに束ねたもの。1日分の形式は main.py の snapshot_payload と
    同じ）をブラウザ側がfetchして検索・一覧表示する完全に静的なページなので、
    results は受け取らない。
    """
    scope_toggle_html = f'''
    <div class="search-panel">
      <p class="search-panel-label"><span>検索条件（すべて同時に絞り込みに使えます）</span></p>
      <div class="field-row">
        <span class="field-caption">タイトルで検索</span>
        <div class="search-box" id="search-box">
          <span class="term-chips" id="term-chips"></span>
          <input type="text" class="archive-search" id="archive-search" placeholder="例: 憲法、選挙" autocomplete="off" />
        </div>
        <div class="suggest-row" id="archive-suggest" hidden></div>
      </div>
      <div class="field-row">
        <span class="field-caption">期間で絞り込み</span>
        <div class="period-selects">
          <select class="archive-date" id="archive-year" aria-label="年で絞り込み"><option value="">すべての年</option></select>
          <select class="archive-date" id="archive-month" aria-label="月で絞り込み" disabled><option value="">すべての月</option></select>
        </div>
      </div>
      <div class="field-row">
        <span class="field-caption">表示する範囲（複数選択可）</span>
        <div class="tier-chips">
{_render_tier_chips()}
        </div>
      </div>
      <div class="field-row">
        <span class="field-caption">会員限定記事</span>
        <button type="button" class="paid-toggle" id="paid-toggle" aria-pressed="false">会員限定記事: 表示中</button>
      </div>
    </div>
    <div class="active-filters" id="active-filters"></div>
    <p class="archive-status" id="archive-status">読み込み中…</p>'''

    main_html = '''
<div id="archive-results"></div>
<button type="button" class="load-more" id="load-more" hidden>さらに過去分を表示</button>'''

    summary_html = (
        '    <p class="summary">過去の社説を横断検索・表示中 <strong id="total-count">0</strong>件</p>\n'
        '    <p class="disclaimer">タイトル・リンク・日付のみ収集。本文は各紙サイトでご覧ください。</p>'
    )
    footer_html = _render_footer()

    return _render_page(
        title="社説まとめ アーカイブ検索",
        description="全国紙・地方紙の社説（オピニオン）を過去分まで横断検索できる非公式アーカイブ。"
                     "タイトル・リンク・日付のみを収集し、本文は掲載していません。",
        canonical_path="archive.html",
        eyebrow="EDITORIAL DIGEST · ARCHIVE",
        crosslink_html=_render_crosslink(".", "本日の社説まとめへ"),
        heading="社説まとめ<br>アーカイブ検索", summary_html=summary_html,
        main_html=main_html, footer_html=footer_html,
        script=_ARCHIVE_SCRIPT_TEMPLATE,
        scope_toggle_html=scope_toggle_html,
    )
