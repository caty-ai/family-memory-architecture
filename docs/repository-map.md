# リポジトリマップ — どこに何があるか

このリポジトリの中身を1枚で見渡すための地図です。「何をするものか」は [README](../README.ja.md) に、設計の理由は [DESIGN.md](DESIGN.md) にあります。ここは「どこにあるか・それは何か」だけを担当します。

---

## ディレクトリ構成

```text
family-memory-architecture/
├── README.md            … 玄関（en/ja/zh/th の4言語）
├── INSTALL.md           … 導入の分岐板（AI に渡す / 手で入れる）
├── docs/                … 用途別ガイドと設計文書（このファイルもここ）
├── scripts/             … 実働スクリプト26本＋テスト一式（Python 標準ライブラリのみ）
├── manifests/           … 「何が存在してよいか」の許可リスト（お手本サンプル）
├── policies/            … 運用ポリシー（クラウド記憶の配分・ジョブの畳み方・モデルカタログ運用）
├── extensions/          … ランタイム別の実験的プラグイン
└── assets/              … README 用の画像
```

---

## scripts/ — 実働スクリプト26本

CLI 23本＋共通ライブラリ3本。すべて外部パッケージ不要で、Python 3 標準ライブラリのみを使います（`run-with-heartbeat` だけ bash）。役割は5グループに分かれます。

### 共有面（コア）

| スクリプト | 役割 |
|---|---|
| `family-hot-generate` | 投書箱イベントから共有面 `family-hot.md` を清書する**唯一の書き手** |
| `family-hot-lint` | 生成された共有面・台帳・投書箱ソースの規約検査 |
| `family-hot-read` | チェックサム契約を確認してから共有面を読む、安全な読み口 |
| `hot-inbox-post` | 共有面行きのイベントを1件1ファイルで投函（秘密スキャン付き） |
| `hot-inbox-reader` | 新着イベントでエージェントを起こす（処理済み台帳・リトライ＋隔離つき） |

### 検索

| スクリプト | 役割 |
|---|---|
| `recall` | 3層（共有面＋ローカル索引＋クラウド記憶）を1コマンドで横断検索 |
| `meili-ingest` | 許可リスト manifest に載った index だけへ投入する、門番つき投入機 |
| `meili-drift-check` | manifest と実 index の突合＋fail-closed 検査（週次想定） |

### 見張り（ジョブ基盤）

| スクリプト | 役割 |
|---|---|
| `watchdog` | manifest 駆動で全ジョブの heartbeat を検査（停滞・失敗・停止を区別） |
| `job-heartbeat` | ジョブが自分の heartbeat JSON を書くための標準出力機 |
| `run-with-heartbeat` | 既存の cron コマンドを包んで heartbeat を自動記録（bash） |
| `backup-dashboard` | heartbeat 群から静的 HTML ダッシュボードを生成 |

### ガード（安全・衛生）

| スクリプト | 役割 |
|---|---|
| `secret-scan` | pre-commit の秘密スキャナ（staged diff／ファイルツリー） |
| `vault-lint` | vault のリンク切れ・レビュー漂流・秘密混入の検査 |
| `write-guard` | 「この情報はどこに書くか」の判定機 |
| `model-catalog-check` | モデルカタログ・member-state・カタログ policy の fail-closed 検査器（CI ゲート） |
| `overlap-lint` | 毎セッション固定注入の中の事実重複を検出 |
| `injection-budget-check` | 固定注入のバイト予算を manifest と突合 |
| `injection-lint` | エージェント別注入 manifest のサイズ・鮮度検査 |
| `content-lint` | 役割別指示ファイルの期限切れ事実・バイト上限検査 |
| `personal-hot-lint` | 個人用 hot cache の検査 |

### その他

| スクリプト | 役割 |
|---|---|
| `capture-shipper` | OpenClaw の capture spool を秘密情報の赤字化を通してから送出 |
| `save-candidate-suggest` | 会話 transcript から記憶保存の候補を提案（Claude Code Stop hook 用） |
| `lib_atomic.py` | クラッシュ安全な状態ファイル書き込みの共通ヘルパ（ライブラリ） |
| `lib_envfile.py` | 設定用 env ファイルを安全に読む共通ヘルパ（ライブラリ） |
| `lib_yamlsubset.py` | lint 用 manifest/config の限定 YAML 構文を fail-closed で読む共通ヘルパ（ライブラリ） |

テストは `python3 scripts/tests/run_tests.py` で一括実行できます（`test_write_guard.py` は集計対象外なので個別に実行します）。

---

## manifests/ — 許可リストのお手本

「載っているものだけが存在してよい」を機械に検査させるための宣言ファイル群です。すべて実環境の値を汎用化した**お手本サンプル**で、自分の環境に合わせて書き換える前提です。

| ファイル | 役割 |
|---|---|
| `meilisearch-indexes.yaml` | 検索面に存在してよい index の唯一の許可リスト（`meili-ingest` の門番） |
| `jobs.yaml` | 見張り対象ジョブの登録簿（`watchdog` の入力） |
| `fixed-injection.yaml` | 1エージェントの毎セッション固定注入のバイト予算 |
| `injection/agent-g.yaml` | エージェント別の注入面契約のお手本 |
| `injection/platform-caps.yaml` | プラットフォーム別の注入上限の中央表（各エージェント manifest が参照） |
| `fixtures/` | 3つの validator を 1 コマンドずつで緑確認できる最小スモーク用 fixture セット |

---

## 目的別・どこから読むか

| したいこと | 入口 |
|---|---|
| 設計思想と失敗モードを知る | [DESIGN.md](DESIGN.md) |
| 手で導入する | [getting-started.md](getting-started.md) |
| AI に導入を任せる | [agent-guide.md](agent-guide.md)（英語・AI 向け） |
| 共有面の生成・検査・読み取りの契約 | [family-hot-usage.md](family-hot-usage.md) |
| 投書箱への投函 | [hot-inbox-usage.md](hot-inbox-usage.md) |
| 横断検索 | [recall-usage.md](recall-usage.md) |
| 検索索引への投入ルール | [meili-ingest-usage.md](meili-ingest-usage.md) |
| 故障の見張りの考え方 | [jobs-framework.md](jobs-framework.md) |
| バックアップの可視化 | [backup-dashboard-usage.md](backup-dashboard-usage.md) |
| vault の衛生管理 | [vault-lint-usage.md](vault-lint-usage.md) |
| 秘密スキャンの使い方 | [secret-scan-usage.md](secret-scan-usage.md) |
| 「どこに書くか」の判定ルール | [memory-write-guard-spec.md](memory-write-guard-spec.md) |
| 注入予算と重複排除の考え方 | [dedupe-mapping.md](dedupe-mapping.md) |
| クラウド記憶の配分ルール | [../policies/supermemory-allocation.md](../policies/supermemory-allocation.md) |
| モデルカタログの運用規約 | [../policies/model-catalog.md](../policies/model-catalog.md) |
| 配布前の準備チェック | [pre-distribution-rc.md](pre-distribution-rc.md)・[distribution-gate.md](distribution-gate.md) |
| Family OS 側との連携契約 | [family-os-liveness-contract.md](family-os-liveness-contract.md) |
