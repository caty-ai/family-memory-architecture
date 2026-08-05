---
title: デデュープ対応表 — 事実クラス → 正本経路
status: final            # 2026-07-04 #4 内容クラス表 v0 受領（issuecomment-4882082423）で★3行を最終化
owner: Agent A
source: docs/DESIGN.md v0.3 §C1・§5 / Issue #2
generated_at: 2026-07-04
revision: v0.3（★3行最終化 — #4 boundary 準拠。v0.2 = 独立レビュー反映）
---

# デデュープ対応表

毎セッション固定注入 ≈29.4KB（実測 2026-07-04: CLAUDE.md 13.6KB[OMC 3.3 + User 10.3] / MEMORY.md 7.2KB / Supermemory ≈2.6KB / OMC hook ≤6KB）から、**1事実=1正本**への一本化ルールを事実クラス単位で定義する。

**スコープ**: 本表は**固定注入面に現れる事実クラスのみ**を扱う。DESIGN §5 の非注入 SoT（KG / GitHub Issues / transcripts / 各プロジェクト repo）は本表の管轄外（それらの正本性は §5 が既定）。

**数値の正**: サイズ目標は `manifests/fixed-injection.yaml` の `target_total_bytes` が単一の正本（現行値 = 28,500B）。旧試算（Phase A = 31,400B 成長停止線 / Phase B = 25,000B、2026-07-04 当時の値）は本文中に履歴として残すのみで、現行の正本ではない。

**凡例**: ★ = family-hot.md の所有クラス（**#4 内容クラス表 v0 で確定** — [boundary 正本コメント](https://github.com/caty-ai/family-memory-architecture/issues/4#issuecomment-4882082423)。Agent B 判定「boundary conflict なし」。原則: **hot.md が所有するのは短い揮発 index+正本ポインタのみ**、durable な本文は所有しない）。

| # | 事実クラス | 例 | 正本 (SoT) | 注入経路（あるべき姿） | 現状の重複 | Phase B アクション |
|---|---|---|---|---|---|---|
| 1 | 安定プロフィール（オーナー） | 名前・役割・Webセミナー・機材・アカウント | `memory/user_*.md`（既存型体系に統一。`profile_*` という新型は作らない） | MEMORY.md index 1行（詳細は遅延ロード） | **3重**: CLAUDE.md「User Profile」節 + Supermemory「User Profile (Persistent)」+ MEMORY.md | CLAUDE.md 節を2行ポインタ化。Supermemory の安定プロフィール entry を forget（§運用ルール4の復旧手順必須） |
| 2 | Agent A アイデンティティ・必須ポリシー本体 | 名前・一人称・距離感・呼称 | `~/.claude/CLAUDE.md`（Identity 節）— **文書化された例外**: DESIGN §5 SoT 表に CLAUDE.md 行はないが、毎セッション必須の人格・ポリシー定義は「ポリシー本体 = CLAUDE.md が SoT」と本表で明示する。§5 への行追加（agent persona/policy → CLAUDE.md）は DESIGN v0.4 提案（文末） | CLAUDE.md 直 | Supermemory に断片あり | CLAUDE.md 正本のまま維持。Supermemory 断片は forget |
| 3 | 働き方ポリシー（合意済み規律） | code_workflow / git protocol / 検索言語 / コンテキスト運用 | `memory/feedback_*.md`（1合意=1ファイル） | CLAUDE.md に**要約+[[ポインタ]]**、詳細は遅延ロード | CLAUDE.md に全文級の詳細が常駐（code_workflow 等で計 ~6KB） | 各 policy ブロックを要約+ポインタへ圧縮。**前提 gate**: 圧縮前に対応する `memory/feedback_<slug>.md` が存在し全文を含むことを検証（overlap-lint の逆方向チェック=正本存在確認。手動チェックリストでも可）。削減見積 2.5–3KB は**要実測** |
| 4 | 環境・インフラ参照 | SSH 先 / キー保管**場所** / ラッパー(glm 等) / サービス構成 | `memory/reference_*.md`（キーの**値**は記載禁止・場所のみ。memory/ 配下を secret-scan 対象に含める件は #10 へ引き継ぎ） | MEMORY.md index 1行 | Supermemory に一部重複（キー保管・Tailscale 等） | **personal-agent-a 内の**重複 entry のみ forget。共有コンテナ（agent-c-family）側は配分ポリシー §3.1 の Agent B ゲート対象 → 保留（apply-plan 保留リスト参照） |
| 5 | ★ 家族の決定・合意 | 憲章 / 家族ルール / 合意済み設計決定 | family-vault（30_decisions / 20_projects） | family-hot.md「recent decisions ≤5」= **揮発 index 行のみ**+正本リンク必須。vault 未昇格の決定は昇格先 Issue/PR を指して `promotion_pending` 明示（#4 §2） | MEMORY.md に憲章系 4-5 行 + Supermemory「Project Knowledge」 | 直近決定は hot.md（index のみ）へ、MEMORY.md は恒久的な哲学ポインタのみ残す（「恒久 vs 直近」の線引きは判断ベースの**規範**であり機械強制しない）。Supermemory 側 forget |
| 6 | ★ 進行中プロジェクト状態 | 各プロジェクトの現在地・ブロッカー | 各プロジェクト dir（README + `_handoffs/`）+ 台帳 `PROJECTS.md` | hot.md「active projects/blockers ≤5」= **家族横断のみ**。Agent A 個人分は PROJECTS.md に残し hot.md へ複製しない。個人項目が家族横断の依存/ブロッカーになった時のみ hot.md から PROJECTS.md をポイント可（#4 §2） | Supermemory「Recent Context」が実質これを毎セッション再注入 = **安定事実の恒常再注入と同型の障害** | **Recent Context のプロジェクト状態系 entry は forget 対象に含める**（残すのは §5 定義の真のエピソード=「あのとき何を話したか」のみ）。（旧記載「>1KB なら再検討」は施行不能のため撤回 — 独立レビュー B3） |
| 7 | エピソード記憶（経緯・文脈） | 「あのとき何を話したか」 | Supermemory（personal-agent-a）**これが本来の専用役割** | SessionStart 注入 + super-search | — | クラス1/2/4/6 の forget により注入サイズは**安定事実分縮小**（試算 2.6KB→≈1.6KB）。エピソード成分は変更なし |
| 8 | 技術メモ・実証手順 | STT 比較 / Swift 検証 / ATS 制約 | `memory/reference_*.md` | MEMORY.md index 1行 | なし（正常） | 変更なし |
| 9 | ★ 全員向け運用注意 | 「今週 X に触るな」等の揮発注意 | **暫定 SoT = 本リポの pinned Issue**（ジェネレーター稼働まで。#4 §2 で確認済み） | ジェネレーター稼働後は hot.md「cautions ≤3」+ 正本リンク。**expiring・owner 必須・恒久注意は policy/docs 行き**（#4 §2。TTL 既定 7日は Agent A 提案値 — #4 Q3 で Agent B 確認待ち） | なし（未整備） | Agent A は #5 の hot-inbox 投函（`caution` event、`expires_at` 必須）で供給。恒久化しそうな注意は policy 昇格 |

## 運用ルール（対応表の使い方）

1. **新しい事実を書く前に**: この表でクラスを判定 → 正本経路にのみ書く。注入面（CLAUDE.md / Supermemory）に「ついで書き」しない。
2. **overlap-lint が検知した重複**: この表に従って正本側を残し、注入面側を削除/ポインタ化する。表にないクラスが出たら表を先に更新する（PR 経由）。
3. **Phase B の実行順（順序固定）**: #4 確定 → ★行を最終化 → CLAUDE.md/MEMORY.md 編集 PR 作成 → クロスレビュー → **PR merge 確認** → 新ポインタ経由で参照が機能することを検証 → **その後に** Supermemory forget 実行 → 実測を manifest cap 引き下げ（Phase B 値）に反映。merge 前に forget を走らせない（両経路同時喪失の防止 — 独立レビュー m7）。
4. **forget の復旧保証（必須手順 — 独立レビュー B2）**: forget は非可逆のため、実行前に対象 entry ごとに (a) 内容が transcripts（DESIGN §5 の会話原文 SoT）または正本ファイルから復元可能であることを確認し、(b) 復元先を forget 記録（ID/カテゴリ/理由）の「理由」欄に併記する。復元可能性を確認できない entry は forget せず保留リストへ。**忘却内容の全文を永続保存しない**原則は維持しつつ、可逆性は transcripts + 正本側で担保する。
5. **スコープ外**: OMC 管理領域（`<!-- OMC:END -->` より上）の書き換え、他エージェントの CLAUDE.md 相当。

## 期待効果（Phase B 完了時の試算 — 目標の正本は manifest）

| ソース | 現状実測 (2026-07-04 夜) | Phase B 提案（確定ドラフト実測） | 根拠 |
|---|---|---|---|
| CLAUDE.md | 15.0KB (User 領域 11.7 — 同日の parallel_work_protocol 追加で **budget gate BLOCKING 中**) | 9.9KB (OMC 3,316B + User **6,592B**) | クラス1 ポインタ化 + クラス3 圧縮（本表の試算に基づく確定値） |
| MEMORY.md index | 7.5KB（cap 7,500 を +31B 超過・BLOCKING 中） | **7,272B**（余裕 3.0%） | user_*/reference_* 追加行を計上した上で hook 行を圧縮 |
| Supermemory 注入 | ≈2.6KB | ≈1.6KB（**見積**。forget 後に実測） | 安定事実 + プロジェクト状態系の forget（クラス1/2/4/6） |
| OMC hooks | ≤6.0KB | ≤6.0KB | スコープ外・変化なし |
| **合計** | **≈31.1KB** | **≈24.8KB ≤ 目標 25,000B（margin ≈220B、2026-07-04 当時の Phase B 試算値。現行 manifest の `target_total_bytes` は 28,500B）** | margin は Supermemory forget の実効削減に依存（独立レビュー Phase B review MAJOR1 反映）。数値の単一正本は manifest |

## DESIGN v0.4 への提案（別 PR・クロスレビュー要）

本 PR では DESIGN.md を触らない（README の規律: 設計変更は専用 PR + クロスレビュー）。Phase B までに以下を DESIGN v0.4 として提案する:

1. §4 M1 完了条件の「固定注入実測 ≤ 目標」の「目標」= `manifests/fixed-injection.yaml` の `target_total_bytes` である旨を明記（独立レビュー B1-c）
2. §5 SoT 表に行追加: 「agent persona・必須ポリシー本体 → SoT: 各エージェントの CLAUDE.md（policy 領域）」（独立レビュー M4）
3. §C1 の実測値（12.6/6.6KB）を「実測の正本は manifest」と付記して陳腐化を解消（独立レビュー n1）
4. §C1 に `target_total_bytes`（aggregate 上限）と dynamic ソースの `alert-only` 区分を機構として追記（独立レビュー n2/M2）
