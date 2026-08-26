# 導入ガイド（Getting Started）

README の[クイックスタート](../README.ja.md#get-started)の詳細版です。対応プラットフォーム・前提条件・導入 Step 1〜6 の全手順・導入後の運用をまとめています。

> **導入を検討する方へ**: このリポジトリは「そのまま `git clone` すれば動く製品」ではなく、**参考アーキテクチャ＋実働コード**です。パスやエージェント名は私たちの環境向けに書かれているので、導入する場合は本ガイドを読んで自分の環境に読み替えてください。考え方(設計原則とポリシー)の部分は、環境が違ってもそのまま使えます。

## 目次

- [対応プラットフォーム](#対応プラットフォーム)
- [前提として必要なもの](#前提として必要なもの)
- [導入方法（Step 1〜6）](#導入方法step-16)
- [導入後の運用](#導入後の運用)

---

## 対応プラットフォーム

この仕組みの中心は「**共有フォルダに置かれたただの Markdown と、シェルから呼べる CLI**」なので、特定の AI 製品にロックインされません。ファイルが読めてシェルが叩ければ、どのエージェントでも参加できます。

| プラットフォーム | 対応状況 | 接続のしかた |
|---|---|---|
| **Claude Code**（Anthropic） | ✅ 実運用中 | SessionStart hook で family-hot.md を毎セッション自動注入。Supermemory は公式プラグイン（claude-supermemory）で自動注入。`recall` はそのまま利用（Meilisearch 層は別途の検索ラッパーを `RECALL_MEM_SEARCH` で指定。同梱していない） |
| **Hermes Agent** | ✅ 実運用中 | サーバー上のエージェントが family-hot 生成プログラムのオーナー。同じ共有フォルダ（Syncthing 同期）を読み書き |
| **OpenClaw** | ✅ 参加可能 | 共有フォルダの family-hot.md / vault を読む＋投書箱に投函する形で参加（ファイル操作ができれば足りるため） |
| その他（Codex CLI、自作エージェント等） | ⭕ 原理的に対応 | 「起動時に family-hot.md を読む」処理を1行入れるだけで最低限参加できます。Supermemory は REST API 経由 |

**ポイント**: 自動注入（hook）の仕組みがあるのは Claude Code だけですが、それは「便利さ」の差であって「参加できるか」の差ではありません。最悪、起動プロンプトに `cat family-hot.md` の結果を貼るだけでも成立します。

---

## 前提として必要なもの

### 必須（これがないと始まらない）

| もの | 用途 | 補足 |
|---|---|---|
| Git / GitHub | 設計文書・Issue・レビューの台帳 | このリポジトリ自体の運用方法（README「Project status」参照） |
| Python 3 | 全スクリプトの実行環境 | 3.14 で実測。3.13 以前は未検証・3.9 では一部テスト不合格を確認。すべて標準ライブラリのみで動作 |
| 常時稼働マシン1台 | family-hot の15分ごと自動生成（cron） | サーバーでも、常時起動のデスクトップ機でも可 |
| ファイル同期の仕組み | 共有フォルダ（vault）を全マシンに配る | 私たちは Syncthing を使用。Dropbox 等でも原理的には可 |
| 共有フォルダ（vault） | 記憶の正本置き場 | ただのフォルダです。Obsidian で開くと閲覧が快適（PARA 構成推奨） |

### 推奨（検索面がそろって真価が出る）

| もの | 用途 | 補足 |
|---|---|---|
| Meilisearch | ローカル全文検索エンジン | macOS は `brew services`、Linux は systemd サービス等で常駐。議事録・作業ログを固有名詞で瞬時に検索する層 |
| ripgrep (`rg`) | grep 層の高速化 | なければ `grep` に自動フォールバックします |

### 任意（なくても動く）

| もの | 用途 | 補足 |
|---|---|---|
| **Supermemory**（Pro プラン） | クラウド長期記憶。セッション開始時の自動注入 | **なくても他の2層で運用できます**。導入する場合はチームでクォータを共有するため、[policies/supermemory-allocation.md](../policies/supermemory-allocation.md)（配分ポリシー）を必ず一緒に導入してください |
| claude-supermemory プラグイン | Claude Code ⇔ Supermemory の接続 | Claude Code 利用時のみ |
| Tailscale 等の VPN | マシン間の安全な接続 | サーバーと手元マシンをつなぐ場合 |

---

## 導入方法（Step 1〜6）

「ホワイトボード（family-hot）だけまず動かす」のが最小構成で、半日あれば試せます。

### Step 1 — 共有フォルダ（vault）を用意する

```bash
mkdir -p ~/family-vault/00_index/hot-inbox
```

これを Syncthing 等で参加マシン全部に同期します。`00_index/` がホワイトボードと投書箱の置き場です。

> **WSL2 / Linux の注意（vault と env ファイルは ext4 に置く）**: vault と `0600` の env ファイルは必ず Linux ファイルシステム側（ext4、例: `~/family-vault`）に置き、`/mnt/c` 配下（Windows ドライブ）には置かないでください。`/mnt/c`（DrvFs）では `chmod` が効かないため、`family-hot-generate`・`capture-shipper`・env ファイル読み込みの `0600` セルフチェックが fail-closed（exit 2）で停止します。また `flock` による二重起動防止（`hot-inbox-reader` など）も DrvFs 上では信頼できません。Windows 側の Obsidian から vault を見たい場合も、vault は ext4 に置いたまま `\\wsl$\<ディストリ名>\home\...` 経由で開いてください。既定の `~/family-vault` はそのままで安全です。

### Step 2 — このリポジトリを clone してスクリプトを確認する

```bash
git clone <このリポジトリ> && cd family-memory-architecture
python3 scripts/tests/run_tests.py   # まずテストが全部通ることを確認
```

> **メモ:** clone と実行は**ホームディレクトリ配下**で行うのが無難です。既定の生成物セルフチェックは、`/tmp` や外付けボリュームなどグループ所有が普段と異なる場所でも、現在のユーザー所有かつ `0600` を保てていれば通ります。`FMA_EXPECT_OWNER` で所有者を固定した運用では、不一致は引き続き exit 2 の停止要因です。テストには Python 3 以外の追加パッケージは不要です。

主なスクリプト（すべて Python 標準ライブラリのみ）:

| スクリプト | 役割 |
|---|---|
| `scripts/hot-inbox-post` | 投書箱にイベント（決定・ブロッカー等）を安全に投函する。秘密情報の混入チェック・種別ごとの書式チェック付き |
| `scripts/family-hot-generate` | 投書箱を読んでホワイトボード（family-hot.md）を清書する（単一書き手の本体） |
| `scripts/family-hot-lint` | ホワイトボードがルール通りか検査する（正本リンク欠落・手書き改変・期限切れの検出） |
| `scripts/family-hot-read` | チェックサム検証付きでホワイトボードを読む（各エージェントの取り込み口） |
| `scripts/recall` | 3層（Supermemory / Meilisearch / grep）をまとめて検索する統一 CLI |

### Step 3 — 生成を cron に載せる（常時稼働マシンで）

```cron
*/15 * * * * flock -n /tmp/family-hot.lock <repo>/scripts/family-hot-generate --vault-root <vault のパス>
```

15分ごとに投書箱を取り込んでホワイトボードを再生成します。`flock` で二重起動を防ぎます。

> **注**: 素の macOS に `flock` は入っていません。`brew install util-linux`（`flock` は `util-linux` に含まれる）を入れるか、launchd での定期実行に置き換えてください。いずれの場合も二重起動防止の仕組みは捨てないでください。Linux / WSL2 には `flock` が最初から入っているため、この置き換えは不要でそのまま使えます。

> **WSL2 の注意（cron は自動起動しない）**: WSL2 では cron デーモンは既定で自動起動しません。`/etc/wsl.conf` に `[boot]` `systemd=true` を書いて systemd を有効化する（cron も systemd timer も使えるようになります）か、Windows 側のスタートアップ等から `sudo service cron start` を流してください。cron が動いていないと、この Step の定期生成は一度も走りません。

### Step 4 — 各エージェントに「起動時に読む」を仕込む

- **Claude Code の場合**: SessionStart hook に `scripts/family-hot-read --path <vault>/00_index/family-hot.md --check` を登録すると、毎セッション自動で文脈に入ります。
- **その他のエージェント**: 起動スクリプトやシステムプロンプト生成時に同コマンドの出力を差し込みます。

### Step 5 —（推奨）検索層を足す

Meilisearch を常駐させ、vault・作業ログを定期的にインデックスします（インデックス構成の宣言は `manifests/` 参照）。その上で `scripts/recall` を PATH に置くと、次の1コマンドで3層横断検索ができます。

```bash
recall "検索したい言葉" --local-only   # ローカル2層のみ（クラウド枠を消費しない）
recall "検索したい言葉"                # Supermemory 併用時は3層
```

検索結果には「どの層でヒットしたか」のラベルが付きます。grep / Meilisearch 層のヒットは正本ファイルへのリンク付きですが、クラウド記憶層（Supermemory）のヒットはサービス内 ID 参照です（正本リンクの強制は未実装）。層別ヒット率は統計ログに貯まります。

### Step 6 —（任意）Supermemory を足す

クラウド長期記憶を足す場合は、**先に** [policies/supermemory-allocation.md](../policies/supermemory-allocation.md) を読み、チーム版に書き換えてから導入してください。API キーの権限がアカウント全体に及ぶこと・検索クエリも利用枠を消費すること（2メーター制）など、実測で判明した落とし穴がすべて書いてあります。

---

## 導入後の運用

導入して終わりではなく、月1回の軽い点検で健全性を保ちます。

| 頻度 | やること | 参照 |
|---|---|---|
| 常時（自動） | family-hot 生成（15分ごと）＋ lint。生成物の末尾に heartbeat（最終生成時刻）が出るので、止まっていればすぐ分かります | `scripts/family-hot-lint` |
| 週次〜月次 | vault の衛生チェック（リンク切れ・秘密情報スキャン） | DESIGN §C4 |
| **月次** | **クォータ実測 probe**: Supermemory の消費量をコンソールで確認して記録。使用率 60% 未満なら通常、超えたらポリシーのゲートに従って絞る | policy §5。記録先は自分の運用ログに（本リポジトリのサンプル構成には同梱していません） |
| 障害時 | 何が落ちても**セッションは止めない**。クラウド層が死んだら残り2層で続行し、保存失敗分はローカルに退避して後で再送 | policy §6（degradation） |

運用ルールの本体は2つだけです:

- **[docs/DESIGN.md](DESIGN.md)** — 全体設計（何をどこに置くか、失敗モードと対策）
- **[policies/supermemory-allocation.md](../policies/supermemory-allocation.md)** — クラウド記憶の配分ポリシー（誰がどれだけ使えるか、枯渇時にどうするか）
