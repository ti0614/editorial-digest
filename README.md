# 社説まとめツール (editorial-digest)

新聞各社の社説（オピニオン）一覧ページを巡回し、当日分のタイトル・
リンク・日付をまとめた**Webページ（`output/today.html`）を生成する**
ツールです。生成したHTMLはそのままブラウザで開けるほか、Claude
Artifacts・GitHub Pages など任意の静的ホスティングに公開して、スマホの
ブラウザなどから閲覧する使い方を想定しています。

## 対象紙を全国紙のみに絞った理由

2026-08-12、対象を全国紙5紙（読売・朝日・毎日・日経・産経）のみに絞った。
以前はブロック紙・地方紙も収録していたが、それらの設定・調査メモは
`archive/all-tiers-sources` ブランチにそのまま残してあり、必要であれば
そこから該当エントリを `sources.yaml` にコピーして復元できる。

## サイトの構成

- 対象は**全国紙5紙**（読売・朝日・毎日・日経・産経）のみです。以前は
  ブロック紙・地方紙も収録し、tierごとに表示/非表示を切り替えるチップ
  ボタンを設けていましたが、2026-08-12に対象を全国紙のみへ絞りました
  （経緯は下記「対象紙を全国紙のみに絞った理由」を参照）。ページ内には
  tier切替チップの実装自体は残っていますが（`sources.yaml` の
  `tier: national` / `block` / `regional` で判定）、national以外の
  エントリが無いため実質チップは機能しません。
- 各紙が発行元サイトで「鍵アイコン」等により会員限定を明示している場合、
  記事タイトルの横に「会員限定」バッジを表示します（`sources.yaml` の
  `paid_selector` で判定、一覧ページに目印が無い紙は `always_paid` で
  常時会員限定扱い）。現在対象の全国紙5紙はいずれも `paid_selector`・
  `always_paid` を設定しておらず、一覧ページ・記事個別ページ上に会員限定
  を示す表示は見つかっていません（朝日新聞は2026-07-22に5記事で本文が
  無料公開されていることを確認済み）。ただし日本経済新聞は本文自体が
  会員限定のため、取得できるのはタイトルのみです（後述）。
  - ヘッダーの「会員限定記事」ボタンで、会員限定記事の表示/非表示を
    切り替えられる（既定は表示）。切り替えると各日付・合計の件数も
    連動して更新される。選択状態はブラウザに保存され、次回訪問時も
    維持される。
- 当日分の社説のみを1つのセクションにまとめて表示します（複数日をまたぐ
  グルーピングや日付ナビは無く、過去分は次の`archive.html`で扱います）。
- **`archive.html`** で過去分を横断検索できます。`today.html`が
  デプロイのたびに生成する日次スナップショットを月ごとに束ねた `archive/{YYYY-MM}.json` として
  GitHub Pages公開用リポジトリに蓄積し、ブラウザ側でfetchしてタイトル
  キーワード検索・tier絞り込みできる仕組みです（サーバー側での検索処理は
  無し）。日々の蓄積で少しずつ検索対象が増えていきます。**検索対象はタイトル
  のみです**——このツールは著作権上の配慮から記事本文を収集していないため、
  本文検索はできません。
- モバイル最適化、ライト/ダークモード両対応、外部CDN・Webフォント不使用
  （自己完結HTML）。

## できること / できないこと

- 取得するのは **タイトル・記事URL・日付のみ** です。本文（著作権のある
  記事全文）は取得・保存しません。ページを読んだ後、リンク先の元記事を
  各紙のサイトで読む形を想定しています。
- 取得前に対象ページの `robots.txt` を確認し、許可されていない場合は
  自動的にスキップします。
- 1件ごとの取得の間に待機時間（既定2秒）を入れ、サイトへの負荷を抑えます。
- 一覧ページの日付表記に時刻が含まれない記事（多くのサイトで、当日分は
  時刻付きだがそれ以前の日は日付のみになる）については、`python main.py
  today` 実行時に記事個別ページを追加で取得し、`<time>` タグから時刻を
  補います（`extract.py` の `enrich_missing_times`）。この追加アクセスにも
  同じ待機時間・`robots.txt` チェックを適用します。記事ページに `<time>`
  タグが無いサイトでは時刻を補えない場合があります。
- `today`が出力するのは **基準日（既定は本日、`--date`で指定可）当日分の
  記事のみ** です。`check`は疎通確認のため、直近7日分（`pubdate.py` の
  `DEFAULT_WINDOW_DAYS` で変更可）を対象に取得件数を表示します。各紙サイトの
  一覧ページには通常2〜3週間分の記事が並んでいますが、対象外の日付のものは
  自動的に除外します。各紙の日付表記（「2026年7月22日」「7/22」「22日」
  「05:00」のみ、等）はバラバラなため、`pubdate.py` の `parse_published_date`
  で正規化してから絞り込んでいます。日付を解釈できなかった記事は、取りこぼしを
  避けるため除外せず含めます。

## 重要な注意（必ず読んでください）

- 対象は全国紙5紙（読売・朝日・毎日・日経・産経）のみで、いずれも
  ネットワークアクセス可能な環境で実際のHTMLを取得して`sources.yaml`の
  URL・CSSセレクタを検証済みです（`verified: true`）。以前収録していた
  ブロック紙・地方紙の設定・調査メモは`archive/all-tiers-sources`ブランチ
  にそのまま残っています。ニュースサイトはリニューアルでHTML構造が
  変わることがあるため、定期的に `python main.py check` で疎通確認する
  ことを推奨します。
- サイトが `robots.txt` で `Crawl-delay` を指定している場合、本ツールは
  これを検出すると既定の待機時間（2秒）より長く空けてからアクセスします
  （`robots.py` の `RobotsChecker.crawl_delay_sec` / `interval_after`）。
- `robots.txt` の取得・解析は Python標準の `urlopen`（UTF-8決め打ち）では
  なく `requests` の文字コード自動判定を使っています。Shift-JIS等で配信
  しているサイトを `UnicodeDecodeError` で誤って「読めない＝拒否」と
  扱わないようにするためです。
- 各新聞社の利用規約でクローリング・自動取得が禁止/制限されている
  場合があります。本ツールは robots.txt に従いますが、それとは別に
  各サイトの利用規約も確認し、私的利用の範囲内でお使いください。
  商用利用・二次配布・記事本文の再配布は想定していません。
- 日経新聞など会員限定記事は、タイトルまでしか取得できない想定です。
  なお日経の robots.txt は CCBot・GPTBot 等のAI学習系クローラーを
  明示的に拒否していますが、`User-agent: *` では本ツールが使う
  User-Agent は許可対象のため取得しています。

## セットアップ

```bash
pip install -r requirements.txt
```

## 使い方

```bash
# 各ソースの疎通確認（ファイルは作らない。まずはこれで動作確認）
python main.py check

# 一部の新聞社だけ確認
python main.py check --only 朝日新聞 毎日新聞

# 当日分のみを取得して output/today.html と
# output/YYYY-MM-DD-today.json を生成
python main.py today

# 対象を絞る／基準日を指定する
python main.py today --only 朝日新聞 読売新聞 --date 2026-07-21

# output/archive.html（アーカイブ検索ページの骨格）のみ生成する
# （ソース取得は行わない。archive/配下のJSONはブラウザ側でfetchする）
python main.py archive-page
```

生成された `output/today.html` をブラウザで直接開くか、
Claude Artifacts・GitHub Pages 等に公開してください。

ある紙の掲載が0件でも取得失敗とはみなしません（発行が遅い時間帯の紙や、
その日は社説を掲載しない紙があり得るため）。`robots.txt` 拒否・取得エラーが
発生した紙は today.html 上には表示されず、JSONスナップショットに理由付きで
記録されます。

## ファイル構成

| ファイル | 役割 |
|---|---|
| `main.py` | CLIエントリーポイント。ソースの読み込み・巡回ループを制御し、`render.py` を呼んでHTMLを書き出す |
| `robots.py` | `robots.txt` の許可判定・`Crawl-delay` をオリジンごとに管理する `RobotsChecker` |
| `fetch.py` | HTTP取得の薄いラッパー（User-Agent・タイムアウト・文字コード自動判定） |
| `extract.py` | 一覧ページのHTMLから記事(`Item`)を抽出し、不足する時刻を記事個別ページから補う |
| `pubdate.py` | 各紙バラバラの日付表記を正規化・直近日数/当日フィルタする共通ロジック |
| `render.py` | 取得結果からWebページ（`output/today.html` / `output/archive.html`）を組み立てるテンプレート |
| `backfill_archive.py` | アーカイブ過去分の一回限りバックフィル用CLI。ページ送りに対応した紙は広いウィンドウで一覧を遡り、`archive/{YYYY-MM}.json`へ書き出す |
| `archive_month.py` | 月別バンドル `archive/{YYYY-MM}.json` の読み書きを共通化した小モジュール |
| `append_archive_day.py` | 日次スナップショットを該当月のバンドルへマージするCLI（CIが実行） |
| `build_archive_index.py` | 月別バンドルから `archive/index.json`（月一覧・日付一覧）を再生成するCLI |
| `sources.yaml` | 各紙のURL・CSSセレクタ・`tier`（national/regional）などの設定 |

## 新聞社を追加・修正する

`sources.yaml` に1エントリ追加するだけで対応できます。

```yaml
- name: 新聞社名
  category: 社説            # その社での呼称（産経は「主張」など）
  tier: regional             # national（全国紙）/ block（ブロック紙）/ regional（地方紙）
  index_url: https://.../editorial/   # 社説一覧ページ
  item_selector: "li.article"          # 一覧内の1記事を指すセレクタ
  title_selector: "h3"                 # タイトル要素（item内の相対セレクタ）
  title_exclude_selector: "span.new"   # タイトルから除去する要素（任意、"New"バッジ等）
  link_selector: "a"                   # リンク要素
  date_selector: "time"                # 日付要素（任意）
  paid_selector: "span.lock-icon"      # 会員限定を示す要素（任意、鍵アイコン等）
  always_paid: false                   # true なら一覧に目印が無くても常に会員限定扱い（任意）
  verified: false
```

セレクタは実際のページの HTML を見ながら調整してください
（ブラウザの開発者ツールで一覧ページを開き、記事1件を囲む要素を探すのが早いです）。

**未取得（`verified: false`）だった新聞社を新たに対応させる場合は、`verified: true`
にする前に必ず記事個別ページを開いて会員限定かどうかを確認してください。**
一覧ページ（特にサイト内検索の結果ページ）には鍵アイコン等の目印が無くても、
記事個別ページを開くと「デジタルプラン等の会員登録が必要」と表示される紙が
あります（岐阜新聞で発生。北日本新聞など既存の`always_paid`紙と同じパターン）。
一覧ページの見た目だけで無料と判断せず、最低2記事は個別ページまで開いて
確認し、会員限定なら`always_paid: true`を設定してください。

## 定期実行・GitHub Pages公開

`.github/workflows/deploy-today.yml` で、`today.html` を1日3回
（05:10 / 11:10 / 19:10 JST）自動生成し、GitHub Pagesに公開する設定を含めています
（`workflow_dispatch` で手動実行も可能）。利用するには、リポジトリの
**Settings > Pages > Build and deployment > Source** を「GitHub Actions」に
設定してください（これだけは手動での一度きりの設定が必要です）。

