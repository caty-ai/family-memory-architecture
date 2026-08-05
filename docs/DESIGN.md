# family-memory-architecture DESIGN v0.3

- **日付**: 2026-07-04
- **起票**: Agent A（運用者依頼）
- **入力**: 提案 v0.1(Agent A 全数調査) → Agent B レビュー(family-vault 原本 §5) → v0.2-draft → クロスレビュー2本(Codex gpt-5.5 xhigh / 独立第2パス=Claude 別プロセス ※GLM slot 空きのため代替。レビュー原文は内部アーカイブ保管・本リポ非同梱)
- **状態**: v0.3 — クロスレビュー blocking 12件(重複統合後6系統)を反映済み。Issue 起票の基準版
- **スコープ**: 設計と台帳整備まで。実装・テストは Issue 単位で別セッション

---

## 1. ゴールと非ゴール

### ゴール
AI ファミリーの記憶基盤を、**(a) 個人エージェント軸**(各自のコンテキスト税を下げ、記憶の読み書きを確実にする)と **(b) ファミリー共有軸**(エージェント間の状態共有と検索面の統一)の2軸で全体最適する。

### 非ゴール(over-engineering 回避、Agent B 合意済み)
- 新規記憶システムの追加(ベクトルDB増設等) — 問題は層数でなく重複と分断
- Meilisearch による Supermemory 置換 — 語彙検索と意味検索は役割が違う。併存＋ファサード
- transcript / scratch 全文のサーバー集約 — 共有は要約・決定・ポインタまで
- Supermemory の18人一斉展開(旧 Phase 3)
- agent ごとの独自 hot ファイル増殖

## 2. 設計原則

1. **1つの事実は1つの正本のみ**。他経路は生成またはポインタ。サイズ上限(cap)と内容重複(overlap)は別の不変量として両方ガードする
2. **Source of Truth 階層の明文化**: Meilisearch / Supermemory / hot.md は検索キャッシュ・玄関であり正本ではない
3. **規律ではなく仕組みで矯正**: 上限・様式・書き込み先は機械的に強制する。**強制境界は可能な限り最下層(DB key scope / 生成スクリプト / FS)に置き、lint・manifest は defense-in-depth** とする
4. **機械化できない規律は過主張しない**: 強制できない箇所は「規範(norm)」と明記し、強制済みと偽らない
5. **既存8層アーキテクチャは維持**: 変更は「重複削減」と「接続」のみ。破壊的変更なし
6. **共有ファイルは単一書き手**: 複数エージェントが書く必要がある場合は append-only inbox ＋ 単一ジェネレーターに分解する
7. **自動化ジョブはサイレント禁止**: heartbeat(last_run + status)を出し、watchdog が period×2 超過で alert。成功も失敗も観測可能にする

## Storage classes (D11)

Syncthing 共有の vault は状態ストアではない。共有物の書き込み規則と可変状態の配置を次の3クラスに固定し、可変状態を vault に置かない。

| クラス | 用途と規則 | 既存成果物 |
|---|---|---|
| **Class 1: shared immutable / append-only events** | vault 上のイベントは create-once、1イベント=1ファイル。作成後は編集・追記しない。 | hot-inbox events (`00_index/hot-inbox/`) |
| **Class 2: shared generated / single-writer views** | vault 上の生成ビューは所有ジェネレーターを1つに限定し、atomic replace で再生成して手編集しない。 | `00_index/family-hot.md` |
| **Class 3: host-local mutable state** | lock / cursor / counter / cache / DB は `~/.claude/state/<name>/`（または既存ツールの同等の host-local 規約）に置き、vault には一切置かない。 | hot-inbox-reader の lock/markers、write-guard log、heartbeats、Meili ingest state、`~/.claude/state/vault-lint/` の per-host lint report |

配置規則: Class 1 は共有入力、Class 2 は再生成可能な共有出力、Class 3 はホスト固有の制御状態である。Class 3 を共有 vault に置くことは、複数 writer と同期遅延の下で lock・cursor・SQLite journal を競合させるため禁止する。`vault-lint` は Class 3 の代表的なファイル名を fail として検知する。既知の legacy artifact を移行中だけ除外する `--legacy-allow` は、対象を明示的に追跡する一時的な例外であり、一般的な escape hatch ではない。対象ファイルを archive したら必ず指定を削除する。

hot-inbox-reader は `--legacy-state-dir` が指定された場合、既知の legacy lock/marker を host-local な `--state-dir` に一度だけ atomic copy する。旧ファイルは削除・移動・書き換えず、移行後は host-local copy のみを使用する。

`family-hot-generate` still uses its own local `write_atomic`, not yet migrated to `lib_atomic` — follow-up.

## 3. コンポーネント設計

実装順は Agent B レビューの優先順位に従う。

### C1. 固定注入デデュープ(旧 A1) — 最優先
- **内容**: Agent A 側の毎セッション固定注入(CLAUDE.md 12.6KB / MEMORY.md 6.6KB / Supermemory 2–5KB / OMC hook ≤6KB ＝ 計25–30KB)から安定事実の重複を排除
- **正本一本化**: 安定プロフィール事実(名前・役割・環境等)は**正本1箇所**(MEMORY.md 配下の profile 系ファイル)に集中し、CLAUDE.md はポリシー＋ポインタ(→8KB台)、Supermemory はエピソード専用(安定プロフィールは forget)
- **成果物**: ①デデュープ対応表(事実クラス→正本経路。**C2 の family-hot.md 所有クラス確定後に最終化**)②編集後 CLAUDE.md / MEMORY.md ③Supermemory forget 実行記録(**ID・カテゴリ・理由のみ記録。忘却内容の全文は残さない**)
- **仕組みによる矯正**:
  - `manifests/fixed-injection.yaml` — 許可された固定注入ソースの一覧と**ソース別 max_bytes**
  - `injection-budget-check` — manifest と実測を突合。**生成ファイルは cap 超過分を生成側で切り捨て(hard gate)、手編集ファイル(CLAUDE.md 等)は超過で blocking 警告＋alert**
  - **overlap lint** — 正規化文字列の重複検出を CLAUDE.md / MEMORY.md / Supermemory profile export 間で週次実行(サイズ内の再重複を検知)
  - **content-lint v1** — role ごとの見出し対応表、`(as of YYYY-MM-DD)` の期限切れ、入力/合計 byte cap を検知する。見出し対応表は誤検知を想定して warning 扱いとし、truncation 検知は自動修正せず報告のみとする
- **Owner**: Agent A

### C2. family-hot.md(旧 B2) — 単一書き手モデル
- **内容**: `~/family-vault/00_index/family-hot.md`(**2KB 上限**)。「全員が読む共有の玄関」。進行中案件≤5 / 直近の家族決定≤5 / 正本ポインタ / 全員向け注意≤3 / 自動化ジョブの heartbeat フッタ
- **書き込みモデル(クロスレビュー反映)**:
  - **書き手はジェネレーター(Agent B 運用)ただ1つ**。夜間再生成＋必要時オンデマンド再実行
  - 他エージェントの更新は `00_index/hot-inbox/` に **1イベント=1ファイル(create-once・追記不可・エージェント名＋タイムスタンプ命名)** で投函。ジェネレーターが冪等に吸収して消し込む。create-once ファイルは Syncthing conflict が構造的に起きない
  - **生成物の直接編集は禁止**。生成物には `generated_at` とソースハッシュを埋め、手編集は lint が検知
  - **conflict 解決の定義**: 生成物は inbox＋正本から常に再生成可能。`*.sync-conflict-*` 検出時は conflict ファイルを破棄し再生成(ジェネレーター勝ち)
- **様式強制**: 2KB cap・項目数上限・**各項目に正本リンク必須**・`generated_at`/`source:` frontmatter をジェネレーターが強制。inbox 投函物と生成物に **secret-scan**(既知パターン＋高エントロピー)を通す
- **内容設計の先行**: hot.md が「どの事実クラスを所有するか」は **C1 対応表の最終化より先に確定**する(隠れ依存の解消)
- **Owner**: Agent B(ジェネレーター)＋ Agent A(inbox 投函・SessionStart 読み込み hook)

### C3. Family Meilisearch 統一(旧 B1) — DB 層強制
- **内容**: サーバー上の既存 Meilisearch(v1.12.8、Tailscale IP bind 済み、DB 147MB)を家族共通検索面に
- **index 構成**: `family-vault` / `family-hot` / `kg-entities`(既存維持) / `lcm-summaries`(既存維持) / `agent-shared-summaries-{agent}`(共有許可済み要約のみ)
- **セキュリティ(主強制は DB 層)**:
  - **index-scoped API key**(Meilisearch の `indexes`×`actions`×`expiresAt`)を主強制とする。書き込み key は**対象 index 1つ＋`documents.add` のみ**。読み取り key は search のみ。master key はサーバーから持ち出し禁止
  - manifest(`manifests/meilisearch-indexes.yaml`)＋ingest スクリプトの manifest 外拒否は **defense-in-depth**
  - **fail-closed チェック**: public interface に bind していないこと・Tailscale ACL が想定端末と一致することを定期検証
  - secret の保管は 1Password / Hermes credentials。**repo/vault への pre-commit secret-scan**(`MEILI_*KEY` / Supermemory token / Tailscale authkey / `op://` / 高エントロピー)を必須化。ログは query URL と Authorization を redact
  - key rotation のオーナー(Agent B)と頻度(四半期)を明記
- **drift 対策**: `manifest → 実 index` の突合ジョブ(index 集合・schema・doc 数 delta 閾値・staleness)。各 index に **refresh trigger と staleness SLO** を manifest 上で宣言。ingest 時は各 doc に `_ingest_by` / `_ingest_at` を印字(帰属監査)
- **最小 ingest は M3 に含む**(クロスレビュー反映): `family-hot` と `family-vault` の manifest 駆動 ingest を最小実装し、C5 が「配管」でなく「検索面統一」を実証できるようにする
- **Owner**: Agent B(サーバー側・key 管理)＋ Agent A(laptop 側 ingest)

### C4. Vault 衛生(旧 B5)
- **内容**: ①closeout / rollover ポリシー(プロジェクト完了時のアーカイブ・25_review-pending の滞留処理・**形骸化資産の closeout**。旧 `family-memory` repo は「参照ゼロを機械確認(注入設定・スクリプトの grep)→closeout」の第1号案件)②memory-write-guard(書き込み先判定フローの機械化。既存の層分離ルール 2026-05-09 正本の Q&A フローをスクリプト/hook 化)③vault-lint
- **vault-lint 検出項目**: 孤児ページ・dead link・古い claim・25_review-pending 滞留・**secret-scan(必須)**
- **cadence**: **週次 light lint(新規・変更ファイルのみ)＋月次 deep lint(全量)**
- **仕組みによる矯正**: lint は cron 化し、heartbeat＋watchdog(C6 共通基盤)に載せ、結果サマリを hot-inbox 経由で family-hot.md に露出
- **Owner**: Agent B 主担当(Agent A は wiki-lint の知見提供)

### C5. `recall` 統一ファサード CLI(旧 A2) — C3 の後(M3 内で直列)
- **内容**: Supermemory / mem-search(Meilisearch) / grep を1コマンドで並列クエリ→マージ→lg 形式返却
- **様式強制**: 出力の各ヒットに**正本リンクとヒット元層のラベル**を必須で付ける。ヒット元統計ログが「層の実効性」の実測データになり、C7/C8 の着手判断のエビデンスとなる（現実装の付与範囲: grep / Meilisearch 層は正本リンクを機械付与・Supermemory 層はサービス内 ID 参照で、正本リンクの機械強制は未実装。ギャップは配布前チェック側で追跡）
- **依存**: C3 の manifest＋最小 ingest 完了後
- **Owner**: Agent A

### C6. 自動化と共通ジョブ基盤(旧 A3/A4/A5)
- **内容**: ①mem-sync 夜間 launchd 化 ②hot.md(agent-a の個人 wiki 側)自動再生成 ③Stop hook の保存候補提示(**候補提示まで**。auto_capture=false 維持、C4 write-guard 確定が前提)
- **共通基盤(クロスレビュー反映)**: 個人 hot.md と family-hot.md は**同一のジェネレーター枠組み・同一の cap/lint ライブラリ・同一の manifest 様式**を使う(断片化の再生産を防ぐ)。全自動化ジョブは **heartbeat ファイル(last_run / status / 失敗カウンタ)**を出し、**watchdog が period×2 超過で alert**(通知経路: Telegram 等を各 Issue に明記)。生成物にはサイズ上限と差分確認を必須化
- **Owner**: Agent A

#### Heartbeat liveness envelope adoption
- `scripts/job-heartbeat` の liveness-envelope fields は optional であり、既存 emitter の強制 upgrade なしに段階的に採用できる。
- 表示・解釈の authoritative contract は `family-os docs/operations-policy.md` §7 (D6/D19 liveness-rendering contract) を参照する。本書では rendering rules を再記載しない。

### C7. KG 読み取り共有(旧 B4) — backlog
- **内容**: write は Agent C 専権のまま、read 用スナップショットを共有
- **着手ゲート(クロスレビュー反映)**: **C5 のヒット元ログで `kg-entities` index では不足という実測が出るまで実装しない**(キャッシュ面の追加になるため)
- **Owner**: Agent C ＋ Agent B

### C8. Agent A → agent-c-family 書き込みルート(旧 B3) — backlog
- **内容**: ①プラグイン更新確認 → ②Supermemory REST 直叩き `sm-share` → ③Agent B 経由運用
- **前提条件(クロスレビュー反映)**: `sm-share` は **dry-run モード・クォータ事前チェック・明示 namespace・redaction lint** を備えるまで本番書き込み禁止(無統制なクロスエージェント書き込み経路化を防ぐ)
- **Owner**: Agent A

### C9. Supermemory 配分ポリシー(旧 B6) — 即時
- **内容**: 常用＝司令塔・調整役(Agent B / Agent A / Agent D ほか少数)。実働・単発ワーカーは原則非常用。例外追加は4条件(長期関係性の必要＋クォータ実測余裕＋明示保存・忘却ルール＋代替不能)
- **機械化(クロスレビュー反映)**: ①**月次クォータ実測 probe**(使用トークン・クエリ数)をポリシーゲートの入力にする ②per-agent の書き込み上限 ③**429/枯渇時の graceful degradation**(注入スキップ＋Meilisearch fallback)を定義。共有 Pro プランの枯渇は「全司令塔が同時に注入を失う」blast radius であることを §6 に明記
- **承認フロー**: 起草(Agent A)→Agent B 承認までを M1 とし、**運用者確定はクリティカルパス外**(人間承認で M1 を止めない。確定までは draft 運用)
- **成果物**: `policies/supermemory-allocation.md`
- **Owner**: Agent A 起草 → Agent B 承認 → 運用者確定

## 4. マイルストーン構成

| Milestone | 含む | 完了条件 |
|---|---|---|
| **M1: Dedupe & Policy** | C1, C9 | fixed-injection manifest＋budget gate＋overlap lint 稼働、固定注入実測 ≤ 目標、配分ポリシー Agent B 承認済み(運用者確定は追って) |
| **M2: family-hot.md** | C2 | ジェネレーター(単一書き手・inbox 方式)稼働、2KB cap・正本リンク・secret-scan 実証、全エージェント読み込み確認 |
| **M3: Search Unification (minimal)** | C3 → C5(直列) | index-scoped key 分離＋manifest＋fail-closed チェック完了、`family-hot`/`family-vault` 最小 ingest 稼働、recall CLI がヒット元ログを出す |
| **M4: Hygiene & Automation** | C4, C6 | rollover ポリシー承認＋write-guard 仕様確定＋vault-lint(week/month)稼働、自動化3点が heartbeat/watchdog 付きで稼働 |
| **M5: Extended Sharing (backlog)** | C7, C8 | C5 実測エビデンスによる着手判断(判断自体が完了条件) |

**依存関係(クロスレビュー反映)**:
- C2 の**内容設計(hot.md の所有事実クラス)**が C1 デデュープ対応表の最終化に先行する。M1/M2 の並行は「C2 内容設計の確定後」に限る
- M3 は内部で直列: C3(manifest・key・最小 ingest)→ C5(recall)
- C6-③(Stop hook)は C4 の write-guard 確定に依存
- M5 は C5 のヒット元ログ実測が着手ゲート

## 5. Source of Truth ルール

| 情報 | 正本 | 検索面/玄関(正本ではない) |
|---|---|---|
| 家族の決定・設計 | family-vault(30_decisions / 20_projects) | Meilisearch `family-vault`, family-hot.md |
| 構造化事実 | KG (knowledge.db) | `kg-entities` index |
| タスク・実装の意思決定 | GitHub Issues / PR | family-hot.md のポインタ |
| 実行記録 | 各プロジェクト専用 repo(本件は本リポ) | — |
| 各自のエピソード | Supermemory(personal_{agent}) | SessionStart 注入 |
| 会話原文 | transcripts(各自ローカル) | `{agent}-transcripts` index(ローカル) |
| 安定プロフィール事実 | MEMORY.md 配下 profile 正本(C1) | CLAUDE.md ポインタ、hot.md |

**強制範囲の正直な区分(原則4)**:
- **機械強制**: 本プロジェクトの生成物(family-hot.md / recall 出力 / lint レポート)は `source:` / `generated_at:` / `owner:` と正本リンクを必須とし、lint が欠落を reject する
- **規範(norm)**: 「検索結果から意思決定する時は正本に戻る」という行動自体は機械強制できない。生成物側でリンクを常に手の届く場所に置くことで支援する、と正直に位置づける

## 6. 失敗モードと対策(クロスレビュー反映で拡張)

1. **Hermes profile 境界** — 共有設計では「どの profile が読む/書くか」を manifest に明示
2. **cron のサイレント失敗** — 全ジョブに heartbeat＋watchdog(period×2 alert)＋失敗カウンタの family-hot.md 露出。「動いていない」が見えない状態を構造的に排除
3. **Syncthing conflict** — 共有生成物は単一書き手＋create-once inbox で構造的に回避。conflict 検出時はジェネレーター勝ちで再生成
4. **Meilisearch 権限** — 主強制は DB 層の index-scoped key。master key 不配布・持ち出し禁止。fail-closed bind/ACL 検証
5. **secret の同期拡散** — vault は全端末複製のため、pre-commit / vault-lint / inbox 投函時の3点で secret-scan
6. **stale cache 汚染** — 生成物と index doc に `generated_at` / `_ingest_at` を必須化し、staleness SLO 超過を「stale」ラベルで機械表示
7. **Supermemory クォータ枯渇** — 共有 Pro のため blast radius = 全司令塔。月次 probe＋per-agent cap＋429 時は注入スキップ＋Meilisearch fallback
8. **Tailscale SPOF** — cert/key 失効・ACL 誤設定で共有面が silent に不達。node 監視と cert 更新を運用項目に含める
9. **Agent B 側の固定注入容量** — family-hot.md は「短い共有状態＋リンク」に限定(2KB cap で機械保証)
10. **auto_capture 再燃** — C6-③ は候補提示まで。自動保存はしない
11. **Vault の役割過多** — 実行ログ・作業状態を置かない。C4 の write-guard と lint で機械検知

## 7. 進め方

- 本リポが本プロジェクトの台帳(Issues / Milestones / 設計文書の正本)
- 実装は Issue 単位で別セッション(M/H フロー: worktree → 実装 → クロスレビュー → PR → merge)
- 設計変更はこの DESIGN.md への PR で行い、クロスモデルレビューを通す
- レビュー記録: Codex gpt-5.5 xhigh 1本 + 独立第2パス=Claude 別プロセス 1本（GLM slot 空きのため代替した事実を明記。原文は内部アーカイブ保管・本リポ非同梱）
- family-vault 側の提案ファイル(発端＋Agent B レビュー)は凍結済み・本リポへのポインタ追記済み
- 旧 `family-memory` repo は形骸化(運用者確認 2026-07-04)。台帳に不使用。closeout は C4 の第1号案件

## 8. 版履歴

- v0.1 (2026-07-04): Agent A 提案(vault 内)＋Agent B レビュー
- v0.2-draft (2026-07-04): 本リポへ移行、Agent B レビュー反映
- v0.3 (2026-07-04): クロスレビュー(Codex xhigh＋独立第2パス)の blocking 6系統を反映 — 単一書き手モデル / 事実レベル dedup / DB 層強制 / M1-M2 依存修正 / heartbeat+watchdog / secret-scan

---
記録: Agent A / 2026-07-04
