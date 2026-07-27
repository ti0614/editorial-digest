# CLAUDE.md

このファイルは、このリポジトリで作業する Claude Code (claude.ai/code) 向けのガイドです。

## 応答言語

Claudeはこのリポジトリで作業する際、ユーザーへの応答を必ず日本語で行うこと。

## これは何か

editorial-digest: 日本の新聞各社の社説・オピニオン一覧ページを巡回し、タイトル・
リンク・日付をまとめた静的な自己完結型HTMLページを生成するスクレイパーです。
著作権上の配慮から、意図的にメタデータ（タイトル・リンク・日付）のみを収集し、
記事本文は一切取得しません。

## セットアップ

```bash
pip install -r requirements.txt
```

## コマンド

```bash
# 各ソースの疎通確認のみ行う（ファイルは一切書き出さない）
python main.py check

# 対象を新聞社名で絞り込んで確認
python main.py check --only 朝日新聞 毎日新聞

# 全ソースを取得し、output/today.html（当日分のみ）+
# output/YYYY-MM-DD-today.json を生成
python main.py today
python main.py today --only 朝日新聞 読売新聞 --date 2026-07-21

# output/archive.html（アーカイブ検索ページの骨格）のみ生成する
# （ソース取得は行わない。archive/配下のJSONはブラウザ側でfetchする）
python main.py archive-page
```

このリポジトリにはテストスイート・リンター・ビルド手順はありません ——
`python main.py check` が最も近いスモークテストです（実サイトへネットワーク
アクセスしますが、ファイルは書き出しません）。

## アーキテクチャ

パイプライン: `sources.yaml` → `main.py`（オーケストレーション） →
`fetch.py`/`robots.py`（通信） → `extract.py`（パース） → `pubdate.py`
（日付正規化） → `render.py`（HTMLテンプレート化） → `output/*.html`。

- **`sources.yaml`** — 新聞社1社につき1エントリ: `index_url`、CSSセレクタ
  （`item_selector`/`title_selector`/`link_selector`/`date_selector`/`paid_selector`）、
  `tier`（`national`/`block`/`regional`）、`always_paid`や`unavailable_reason`
  といったフラグを持つ。新聞社を追加する場合、通常はここにエントリを足すだけで
  コード変更は不要。`verified: true/false`は、そのセレクタが最近実際のHTMLに
  対して確認済みかどうかを示す。社説専用の一覧ページが無い新聞社については、
  `index_url`にサイト内全文検索の結果ページを指定することもできる（例:
  岐阜新聞の`?fulltext=社説`）。`title_prefix`は検索語をたまたま含むだけの
  無関係な記事を除外し、`title_strip_pattern`（正規表現）は検索結果UIが
  埋め込むタイトル文言（「社説」という接頭辞、末尾の括弧付き日付）を除去する。
  **`verified: false`だった新聞社を新たに対応させる際は、`verified: true`に
  する前に必ず記事個別ページを（最低2記事）開いて会員限定かどうか確認する
  こと。**一覧ページ（特に全文検索の結果ページ）に鍵アイコン等の目印が無くても、
  記事個別ページでは「デジタルプラン等の会員登録が必要」と表示される紙がある
  （岐阜新聞で発生。北日本新聞など既存の`always_paid`紙と同じパターン）。
  一覧ページの見た目だけで無料と判断しないこと。
- **`main.py`** — CLIエントリーポイント（`check` / `today` / `archive-page` サブ
  コマンド）。ソースを読み込み、`_iter_results`/`process_source`で1件ずつ処理し、
  JSONスナップショット＋HTMLを書き出す。`process_source`は1ソースの失敗を
  `SourceResult.error`に格納するだけで、実行全体は中断しない。ソース間では
  `robots.interval_after(...)`分だけ待機してリクエストを抑制する。
- **`robots.py`** — `RobotsChecker`が`robots.txt`をオリジンごとにキャッシュし、
  `allows(url)`で許可判定を行う（`robots.txt`が読めなかった場合は安全側に倒して
  拒否）。サイトが`Crawl-delay`を指定していればそこから待機秒数を算出する。
- **`fetch.py`** — `requests`の薄いラッパー（固定`User-Agent`、タイムアウト、
  文字コード自動判定）。一部サイトがShift-JISで配信しており`urlopen`だと
  UTF-8決め打ちで誤デコードするため、意図的に`urllib`ではなくこちらを使用。
- **`extract.py`** — `extract_items()`が、`sources.yaml`のセレクタを使って
  1ソース分の一覧ページHTMLを`Item(title, link, published, paid)`にパースし、
  その過程で`within_window`（または当日モードでは`is_same_day`。後述）
  で絞り込む。`enrich_missing_times()`は second pass で、一覧ページの日付に
  時刻が無い記事について、記事個別ページを取得して`<time>`タグや本文中の
  日付+時刻表記から時刻を補う。
- **`pubdate.py`** — 日付パースの中核。各紙で日付表記がバラバラなため
  （「2026年7月22日」「7/22」「22日」「時刻のみ」等）、`parse_published_date()`
  が`reference_date`を基準にすべて正規化し、素朴にパースした結果が未来日に
  なる場合は前年・前月に補正する。`within_window`（`check`/`today`の既定の
  直近日数フィルタ、`backfill_archive.py`は独自のウィンドウ幅で呼び出す）
  と`is_same_day`（today.html用）はどちらもこのパーサーの上に構築されており、
  どちらも解釈できない日付は既定で除外せず含める方針 —— 記事を静かに
  取りこぼす方が、過剰に含めてしまうより悪いという判断。
- **`render.py`** — 純粋なテンプレート化: `list[SourceResult]`を自己完結型の
  HTML文字列に変換する（インラインCSS/JS、外部CDN・Webフォント不使用）。
  `render_today_html()`が`today.html`を生成する —— セクションは
  1つのみで日付ナビは無く、ある紙が0件でも失敗扱いにはしない（新聞社に
  よっては毎日社説を掲載するとは限らないため）。tier切替チップ・会員限定
  トグルは3種（national/block/regional）の表示/非表示を body classes +
  localStorageでクライアント側に保存する。`render_archive_html()`が横断
  検索用の`archive.html`を生成する —— 記事データをビルド時に埋め込まず、
  `archive/index.json`・`archive/{date}.json`をブラウザ側でfetchして検索・
  表示する完全に静的なページ（詳細は後述）。タイトル検索・日付絞り込み・
  tier切替・会員限定トグルの4条件を1つの検索パネルにまとめ、選択中の条件を
  ＋でつないだ要約バー（AND条件で絞り込めることの可視化）を表示する。
- **`build_archive_index.py`** — `archive/`配下にあるスナップショットJSONの
  ファイル名一覧から`archive/index.json`を再生成する小さなCLIスクリプト。
  CIが当日分を`archive/{date}.json`としてコミットした直後に実行する。

### 週間ダイジェスト(digest.html)を廃止した理由

かつて`main.py run`が直近1週間分をまとめた`output/digest.html`を生成していたが、
実際にはデプロイワークフロー（`deploy-today.yml`）が一度も参照しておらず本番公開
されたことが無かった。一方`archive.html`が日付ごとのグルーピング・tier切替・
会員限定トグルという表示形式に加え複数年分の横断検索まで持つようになり、
digest.htmlの表示内容を機能的に包含する状態になったため、`run`サブコマンドと
`render_html()`ごと削除した。同じ判断のもと`sources.yaml`/READMEにある紙単位の
記載も1週間分を前提にしていた説明を`today`/`archive`基準に書き換えている。

### today.htmlの絞り込み

`process_source()`は`same_day_only`フラグを取る。これを設定すると、基準日への
絞り込みが`enrich_missing_times()`より*前*に行われるため、today.htmlでは、
どのみち捨てられる古い記事のために記事個別ページへ余計なリクエストを送らずに
済む —— この順序は正確性・リクエスト数の両方に関わる。

### アーカイブの永続化

`output/`は`.gitignore`対象で、`main.py today`が生成するJSONスナップ
ショットはリポジトリに残らない（GitHub Pagesへのデプロイも毎回総入れ替え
のため、CI実行が終わると前日以前のデータは消える）。横断検索用のアーカイブは
これとは別に、CIワークフロー（`deploy-today.yml`）が`output/{date}-today.json`
を`archive/{date}.json`としてコピーし、専用の**`data`ブランチ**にコミット・
pushすることで永続化している。`main`はコード用ブランチとして
PRレビュー必須のルールセット保護がかかっているが、`data`はそのルールセットの
対象外（`main`のみ対象）なので、bypass設定を一切追加せずにCIから直接push
できる。デプロイのたびに`data`ブランチの`archive/`一式を`_site/archive`へ
コピーしてGitHub Pagesに公開する（`build_archive_index.py`がその都度
`archive/index.json`＝日付一覧を再生成する）。

### コードに組み込まれたコンプライアンス方針

- すべての取得はまず`RobotsChecker`経由で`robots.txt`を確認する。拒否された
  ソースはスキップし（`SourceResult.skipped_by_robots`）、強制的には取得しない。
  `sources.yaml`/READMEには、`robots.txt`でClaude/Anthropic系クローラーを
  名指しで拒否している特定の新聞社が記載されており、これらは意図的に未実装の
  ままにしている（回避策を取らない）。これは、このツール自身のUser-Agent
  （`EditorialDigestBot/0.1`）がそれらのルールに文字通り一致しない場合でも、
  また本番運用がライブのClaudeセッションではなくGitHub Actions経由で行われる
  想定であっても変わらない —— サイト側が表明している意思はAnthropic/Claudeの
  関与そのものについてであり、どのインフラがリクエストを発行するかの話では
  ないこと、また、スクレイパーの構築（セレクタの選定等）自体が結局はClaude
  セッションによる直接のページ取得を要すること、が理由。これらのソースを
  `sources.yaml`に追加しない、かつユーザーが改めて明示的に持ち出さない限り
  この方針を再検討しないこと。
  - 取得するのはタイトル・リンク・日付のみで、記事本文HTMLは保存しない。
- リクエストは間隔を空ける（既定はソース間2秒、`Crawl-delay`の指定があれば
  それ以上）。
