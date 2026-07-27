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
.archive-search, .archive-date {
  width:100%; font: inherit; font-size:0.95rem; padding:0.6rem 0.75rem; border-radius:8px;
  border:1px solid var(--rule); background:var(--bg); color:var(--ink);
}
.archive-search:focus-visible, .archive-date:focus-visible { outline:2px solid var(--accent); outline-offset:2px; }
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

# アーカイブ検索ページ専用のスクリプト。他の2ページと違いサーバー側で記事を
# 埋め込まず、archive/index.json・archive/{date}.json をブラウザ側でfetchして
# 組み立てる。tier/会員限定トグルは_SCRIPT_TEMPLATEと同じロジックだが、
# 動的に追加されるセクションに対してupdateCountsを呼び直す必要があるため
# 独立したスクリプトにしている。
_ARCHIVE_SCRIPT_TEMPLATE = r"""
(function () {
  var TIERS = ['national', 'block', 'regional'];
  var DEFAULT_ON = { national: true, block: false, regional: false };
  var TIER_LABEL = { national: '全国紙', block: 'ブロック紙', regional: '地方紙' };
  var WEEKDAY_JP = ['月', '火', '水', '木', '金', '土', '日'];
  var PAGE_SIZE = 30;

  var body = document.body;
  var totalEl = document.getElementById('total-count');
  var resultsEl = document.getElementById('archive-results');
  var searchInput = document.getElementById('archive-search');
  var dateFilterInput = document.getElementById('archive-date-filter');
  var loadMoreBtn = document.getElementById('load-more');
  var statusEl = document.getElementById('archive-status');
  var filtersEl = document.getElementById('active-filters');
  var chips = {};
  TIERS.forEach(function (t) { chips[t] = document.querySelector('.tier-chip[data-tier="' + t + '"]'); });

  var allDates = [];
  var loadedCount = 0;
  var dateFilter = null;

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
    // 「さらに過去分を読み込む」や日付ジャンプで後から追加される記事にも
    // 現在の検索クエリを適用する必要があるため、search-hideの付与は
    // searchInputのinputイベントではなくここで毎回全件に対して行う
    // （updateCountsはコンテンツ追加のたびに呼ばれるため、ここに置けば
    // 新規追加分にも自動的に反映される）。
    if (!searchInput) return;
    var q = searchInput.value.trim().toLowerCase();
    resultsEl.querySelectorAll('li.article-item').forEach(function (li) {
      var match = !q || li.getAttribute('data-title').indexOf(q) !== -1;
      li.classList.toggle('search-hide', !match);
    });
  }

  function updateCounts() {
    applySearchFilter();
    var grandTotal = 0;
    resultsEl.querySelectorAll('section.dategroup').forEach(function (sec) {
      // 日付フィルタで除外中のセクションはhidden状態を保ったまま完全にスキップする
      // （offsetParentベースの計測対象に含めない・以下のhidden解除もしない）。
      if (sec.classList.contains('date-filtered-out')) { return; }
      // offsetParentは祖先がhiddenだと常にnullになるため、計測前に一旦
      // hiddenを解除しておく（そうしないと一度0件と判定されたセクションが
      // 以後ずっと0件のまま隠れ続けてしまう）。
      sec.hidden = false;
      var count = 0;
      sec.querySelectorAll('li.article-item').forEach(function (li) {
        if (li.offsetParent !== null) count++;
      });
      grandTotal += count;
      var countEl = sec.querySelector('.date-count');
      if (countEl) countEl.textContent = count + '件';
      sec.hidden = count === 0;
    });
    if (totalEl) totalEl.textContent = grandTotal;
    renderActiveFilters(grandTotal);
  }

  function renderActiveFilters(total) {
    // 上部の検索条件パネルと同じ並び順（タイトル→日付→表示する範囲→会員限定）で
    // アクティブな条件を＋でつないだ要約を表示し、AND条件で絞り込めることを
    // 可視化する。全国紙のみを「既定表示」として特別扱いせず、ブロック紙のみ・
    // 地方紙のみと同様に選択中のtierは常にそのまま示す（0個選択時は「選択なし」）。
    if (!filtersEl) return;
    var chipsHtml = [];
    var q = searchInput ? searchInput.value.trim() : '';
    if (q) {
      chipsHtml.push('<span class="filter-chip">タイトル「' + esc(q) + '」</span>');
    }
    if (dateFilter) {
      // アーカイブは複数年分をまたぐため、月日だけだと年があいまいになる
      // （例:「7/26」が2024年なのか2026年なのか判別できない）。年を省略せず表示する。
      var p = dateFilter.split('-');
      chipsHtml.push('<span class="filter-chip">' + parseInt(p[0], 10) + '/' + parseInt(p[1], 10) + '/' + parseInt(p[2], 10) + '</span>');
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

  function finishLoading() {
    statusEl.textContent = allDates.length ? 'すべて表示中' : 'まだアーカイブがありません。';
    loadMoreBtn.hidden = true;
  }

  function loadNextPage() {
    var batch = allDates.slice(loadedCount, loadedCount + PAGE_SIZE);
    if (batch.length === 0) { finishLoading(); return; }
    statusEl.textContent = '読み込み中…';
    loadMoreBtn.hidden = true;
    Promise.all(batch.map(function (d) {
      return fetch('archive/' + d + '.json').then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) { return data ? { date: d, items: flattenDateData(data) } : null; })
        .catch(function () { return null; });
    })).then(function (results) {
      results.forEach(function (r) {
        // 日付フィルタによる直接取得で既にレンダリング済みの日付は
        // 重複して追加しない。
        if (r && !document.getElementById('d-' + r.date)) {
          resultsEl.appendChild(renderSection(r.date, r.items));
        }
      });
      loadedCount += batch.length;
      if (dateFilter) {
        // 読み込み中に日付フィルタが設定された場合、新規追加分にも適用する。
        showOnlyDate(dateFilter);
        return;
      }
      updateCounts();
      if (loadedCount >= allDates.length) {
        finishLoading();
      } else {
        statusEl.textContent = loadedCount + '日分を表示中';
        loadMoreBtn.hidden = false;
      }
    });
  }

  if (loadMoreBtn) {
    loadMoreBtn.addEventListener('click', function () { loadNextPage(); });
  }

  if (searchInput) {
    searchInput.addEventListener('input', function () {
      updateCounts();
    });
  }

  function updateLoadMoreVisibility() {
    if (loadedCount >= allDates.length) {
      loadMoreBtn.hidden = true;
    } else {
      statusEl.textContent = loadedCount + '日分を表示中';
      loadMoreBtn.hidden = false;
    }
  }

  function applyDateFilter(dateStr) {
    dateFilter = dateStr || null;

    if (!dateFilter) {
      resultsEl.querySelectorAll('section.dategroup').forEach(function (sec) {
        sec.classList.remove('date-filtered-out');
      });
      updateCounts();
      if (loadedCount >= allDates.length) { finishLoading(); } else { updateLoadMoreVisibility(); }
      return;
    }

    var existing = document.getElementById('d-' + dateFilter);
    if (existing) {
      showOnlyDate(dateFilter);
      return;
    }

    statusEl.textContent = '読み込み中…';
    loadMoreBtn.hidden = true;
    fetch('archive/' + dateFilter + '.json').then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (dateFilter !== dateStr) { return; } // 取得中に別の日付へ変更された
        if (data && !document.getElementById('d-' + dateFilter)) {
          resultsEl.appendChild(renderSection(dateFilter, flattenDateData(data)));
        }
        showOnlyDate(dateFilter);
      })
      .catch(function () {
        statusEl.textContent = 'この日付のデータを読み込めませんでした。';
      });
  }

  function showOnlyDate(dateStr) {
    resultsEl.querySelectorAll('section.dategroup').forEach(function (sec) {
      var match = sec.id === 'd-' + dateStr;
      sec.classList.toggle('date-filtered-out', !match);
      sec.hidden = !match;
    });
    updateCounts();
    loadMoreBtn.hidden = true;
    var parts = dateStr.split('-');
    statusEl.textContent = parseInt(parts[1], 10) + '/' + parseInt(parts[2], 10) + '（' + weekdayOf(dateStr) + '）のみ表示中';
  }

  if (dateFilterInput) {
    dateFilterInput.addEventListener('change', function () {
      applyDateFilter(dateFilterInput.value);
    });
  }

  fetch('archive/index.json').then(function (r) { return r.json(); }).then(function (data) {
    allDates = (data.dates || []).slice().sort().reverse();
    if (dateFilterInput && allDates.length) {
      dateFilterInput.min = allDates[allDates.length - 1];
      dateFilterInput.max = allDates[0];
    }
    loadNextPage();
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
    archive/index.json・archive/{date}.json（CIがコミットする日次スナップショット、
    main.py の write_json と同じ形式）をブラウザ側がfetchして検索・一覧表示する
    完全に静的なページなので、results は受け取らない。
    """
    scope_toggle_html = f'''
    <div class="search-panel">
      <p class="search-panel-label"><span>検索条件（すべて同時に絞り込みに使えます）</span></p>
      <div class="field-row">
        <span class="field-caption">タイトルで検索</span>
        <input type="search" class="archive-search" id="archive-search" placeholder="例: 憲法、選挙" autocomplete="off" />
      </div>
      <div class="field-row">
        <span class="field-caption">日付で絞り込み</span>
        <input type="date" class="archive-date" id="archive-date-filter" aria-label="日付で絞り込み" />
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
    <p class="disclaimer">検索対象はタイトルのみです（本文は収集していないため検索できません）。</p>
    <div class="active-filters" id="active-filters"></div>
    <p class="archive-status" id="archive-status">読み込み中…</p>'''

    main_html = '''
<div id="archive-results"></div>
<button type="button" class="load-more" id="load-more" hidden>さらに過去分を読み込む</button>'''

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
