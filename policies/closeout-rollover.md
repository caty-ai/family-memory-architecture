# Closeout / Rollover ポリシー v1.0 (DESIGN v0.3 §C4 / Issue #9)

- 起草: Agent A 2026-07-06
- 状態: **確定 v1.0** — Agent B 承認 2026-07-06（Issue #9 コメント）+ オーナー確定 2026-07-12（チャット GO）
- 正本: 本ファイル（caty-ai/family-memory-architecture/policies/closeout-rollover.md）
- 関連: [[../docs/memory-write-guard-spec.md]] / vault `50_references/2026-05-09-knowledge-memory-layer-separation-rules.md`

## 0. 目的

第2の脳を腐らせない。「終わったもの」「形骸化したもの」が現役の顔をして検索面・注入面に居座ることを、規律でなく手順とジョブで防ぐ。

## 1. 用語

| 用語 | 意味 |
|---|---|
| **closeout** | 資産（repo / vault ディレクトリ / インデックス / ジョブ）を「完了・終息」として封印する処理。参照可能なまま書き込み・運用を停止する |
| **rollover** | プロジェクト完了時に、残す知識を正本へ昇格し、作業残骸をアーカイブへ移す仕分け処理 |
| **形骸化資産** | 運用参照ゼロだが存在し続けている資産。検索ノイズ・誤参照・secret 残留のリスク源 |

## 2. プロジェクト完了時の rollover 手順

完了宣言（オーナー or 担当エージェント）後、オーナーが以下を実施:

1. **知識の昇格**: 恒久判断・設計・教訓を正本へ移す
   - 家族決定 → vault `30_decisions/`（1決定=1ファイル）
   - 手順・失敗パターン → Skill / personal-wiki
   - プロジェクト経緯の要約 → プロジェクト repo README 末尾（SoT はそのまま repo）
2. **台帳の更新**: PROJECTS.md 該当行を Active から外し、必要なら Standby へ1行で残す
3. **作業残骸の処分**: worktree 削除・一時ブランチ削除・scratch は TTL に任せる
4. **検索面の扱い**: closeout 時に Meilisearch を手で触らない。vault ファイルが `90_archive/` へ移動すれば次回 ingest で新パスの doc が入り、旧パス doc は孤児になる — 孤児の掃除は drift-check の検出 → server 側削除（#6 で定義済みの経路）が担い、closeout 手順側に検索面の作業は発生しない。Supermemory は完了プロジェクトの episodic を四半期見直しで forget 候補に載せる
5. **closeout 記録**: 下記 §4 のチェックリスト結果を該当 Issue または vault 決定ファイルに残す

## 3. 25_review-pending 滞留処理

vault `25_review-pending/` は「レビュー待ち」専用であり、置き場ではない。

- **30日超**: vault-lint (#10) が warning。オーナーは昇格（30_decisions / 50_references へ）・破棄・期限延長のいずれかを選ぶ。延長する場合は frontmatter に `review-by: YYYY-MM-DD` を明記
- **90日超**: vault-lint が fail-level。放置は月次 deep lint のレポートで family-hot（hot-inbox 経由）に露出する
- 破棄は削除でなく `90_archive/review-expired/` への移動 — **append-only は「内容を失わない」の意**（場所の移動は可、削除は不可）。vault は git 管理外のため、移動前に tar バックアップ規律に従う

## 4. 形骸化資産の closeout 手順（機械確認つき）

**判定は grep、宣言は人間** — 「使っていないはず」を規律でなく機械確認で示す。

チェックリスト（実行コマンドと結果を記録に残す）:

1. **参照ゼロの機械確認**: 注入設定（CLAUDE.md / settings.json / hooks）・`~/.claude/scripts`・PROJECTS.md・オートメモリ・vault ナビ（`00_index/`）を対象に資産名で grep。ヒット = 参照を先に剥がす
   - 注意: 検索パターンの `\b` はハイフン境界にマッチする（`family-memory\b` は `family-memory-architecture` に誤ヒット）。除外パターンか `[^-]` で派生名を弾くこと（2026-07-06 実地で確認）
2. **最終更新の確認**: 資産の最終コミット / mtime が 30日以上前であること（アクティブ資産の誤 closeout 防止）
3. **secret 残留スキャン**: closeout 前に `scripts/secret-scan` を資産全体へ実行。残留があれば closeout でなく先に無害化（revoke）
4. **封印**: GitHub repo → Archive（読み取り専用化・可逆）/ vault ディレクトリ → `90_archive/` へ移動 + 元位置にポインタ 1 ファイル / ジョブ → cron/launchd 解除 + jobs.yaml から登録削除（監視レジストリの変更であり記憶の削除ではない。内容は本ポリシーと Issue 記録に残る）
   - **封印の検証**: closeout 記録は封印の機械確認が取れるまで「pending」と明記する（例: `gh repo view <repo> --json isArchived` が true / 移動先にファイル実在 / jobs.yaml に該当行なし）。宣言と実態の乖離を記録上に残さない
5. **記録**: 実施日・確認コマンド・承認者を Issue コメントまたは vault `30_decisions/` に残す

### 第1号適用: 旧内部 repo（2026-07-06 実施）

- 形骸化確認: オーナー 2026-07-04
- 参照ゼロ機械確認: 2026-07-06 Agent A 実施 — `~/.claude/CLAUDE.md` / `~/.claude/scripts` / `~/.claude/settings.json` / hooks / PROJECTS.md / オートメモリ / vault `00_index/where-to-write.md` の全てで運用参照ゼロ（歴史的言及は対象外）。最終更新 2026-06-10（30日基準は僅かに未達だが、更新実体は README 整理のみで運用実体なし — 例外としてオーナー確認済みの形骸化宣言を優先）
- secret スキャン: ローカル clone なし・アーカイブ操作のみのため対象外（repo 内容は封印後も GitHub で読み取り可）
- 封印: **確定** — 2026-07-12 オーナー GO により Agent A が `gh repo archive <repo> -y` を実行。機械検証: `gh repo view <repo> --json isArchived` → `true`（2026-07-12 実測）
- 記録: 本ファイル + Issue #9 コメント

## 5. 四半期 rollover レビュー

Meilisearch key rotation（四半期・owner Agent B）と同じ周期で:
- PROJECTS.md Active の棚卸し（動いていない行の Standby 降格）
- Supermemory forget 候補の選定（完了プロジェクト episodic）
- 90_archive 行きの review-expired 処分確定

## 6. 承認

- [x] Agent B 承認（Issue #9 コメント 2026-07-06）
- [x] オーナー確定（draft → v1.0、2026-07-12 チャット GO）
