# memory-write-guard 仕様 v1.0 (DESIGN v0.3 §C4 / Issue #9)

- 起草: Agent A 2026-07-06
- 状態: **確定 v1.0**（仕様のみ。実装は仕様承認後の別 Issue — Issue #9 スコープ定義に従う。Agent B 承認 2026-07-06 + オーナー確定 2026-07-12）
- 上位正本: vault `50_references/2026-05-09-knowledge-memory-layer-separation-rules.md`（層分離ルール v0.2）。本仕様はその Q&A フローの機械化定義であり、層の定義自体は変更しない

## 0. 目的と非目的

- **目的**: 「この情報はどこに書くか」の判定を、人が都度思い出す規律から、聞けば答えが返る機械へ移す（DESIGN 原則3）
- **非目的**: 自動保存（auto_capture は false を維持、DESIGN 失敗モード10）。write-guard は**判定と提案**まで。書き込み実行は常に呼び出し側

## 1. 提供形態

| 形態 | 用途 | 実装 Issue |
|---|---|---|
| CLI `write-guard "<書きたい内容の1行説明>" [--type <hint>] [--json]` | エージェントが保存前に自問する / Stop hook が呼ぶ | 別 Issue（実装） |
| ライブラリ関数 `route(description, attrs) -> Route` | ingest / save 系スクリプトへの組み込み | 同上 |

## 2. 判定モデル — 質問は最大4つ

層分離ルール v0.2 §1-§3 の表を、順序付き決定木に正規化する:

```
Q1. secret か?（API key / token / password / 顧客機微）
    yes → 書き込み拒否。--> .env / credential store / 1Password。
          記憶レイヤーには「場所と取り扱いルール」のみ許可         [原則C]
Q2. 一時的か?（今セッション・今日の作業でしか使わない）
    yes → Route {layer: "none", path_hint: "scratch/session ログ/daily note", ...}
          を返す（空オブジェクトではなく「保存不要」を明示する定常 schema。
          呼び出し側はこの Route を受けて何も書かないのが正）
Q3. 恒久情報の種類は?（--type ヒントまたはキーワード分類）
    decision   → vault 30_decisions/（1決定=1ファイル）+ 必要なら hot-inbox 投函
    profile    → MEMORY.md 配下 profile 正本（C1 デデュープ対応表に従う）
    procedure  → Skill（検証済み手順）/ personal-wiki（知見・パターン）
    structured → KG（entity/relation。write は Agent C 専権 → 依頼経路を提示）
    project    → 該当プロジェクト repo（Issue / README / handoff）
    reference  → vault 50_references/ または 25_review-pending/
                 （review-by は**呼び出し側が明示指定**。guard は欠落を拒否するのみで
                  日付の自動補完はしない — 補完は enforcement-vs-norm 区分違反）
    episodic   → Supermemory personal_{agent}（短い要約+正本リンクのみ）
Q4. 共有範囲は?（自分だけ / 家族全員）
    家族全員 → 正本を共有面（vault / KG）に置き、個人面にはポインタ
    自分だけ → 個人面（MEMORY.md / personal-wiki / personal_{agent}）
```

出力（Route）: `{layer, path_hint, format_hint, caveats[]}`。
例: decision → `{layer: "family-vault", path_hint: "30_decisions/YYYY-MM-DD-<slug>.md", format_hint: "1決定=1ファイル+frontmatter", caveats: ["hot-inbox 投函は create-once", "本文は要約+正本リンク"]}`

## 3. 機械強制と規範の区分（DESIGN 原則4）

- **機械強制できる**: secret 検出（scripts/secret-scan 再利用）→ 拒否 / Supermemory 向け本文の長さ上限（>10行で警告）/ 25_review-pending への書き込みに review-by 必須
- **規範に留まる（正直に明記）**: 「提案された層に実際に書くか」は呼び出し側の自由。write-guard は監査ログ（判定履歴 JSONL）を残し、月次 probe の入力にする

## 4. Stop hook 統合（#11 C6-③ の前提仕様）

- Stop hook はセッション終端で「保存候補」を抽出し、各候補を write-guard に通して**提案のみ**表示する:
  `候補: 「GLM の effort 実測」→ reference / personal-wiki（理由: 再利用可能な実測知見）`
- 候補抽出の対象: 決定文言（「〜に決定」「方針」「今後は」）・実測値・新規の失敗パターン
- **表示前 secret フィルタ**: 候補の抜粋文字列は表示前に secret-scan 相当の検査を通し、
  ヒットした候補は表示自体を抑止する（コンソールへの secret 露出防止）。抽出はメモリ内
  一過性で、hook はいかなる永続化もしない
- auto_capture=false 維持: hook は書き込み API を一切呼ばない

## 5. 実装受け入れ条件（実装 Issue に引き継ぐ）

- [ ] 層分離ルール v0.2 の表とこの決定木の対応が1対1でレビュー可能（乖離したらどちらかを直す。二重定義禁止）
- [ ] secret 検出で拒否した場合、内容をログにも残さない（判定履歴には rule 名のみ）
- [ ] `--json` 出力が安定 schema（Route）
- [ ] 判定履歴 JSONL は `~/.claude/state/write-guard/decisions.jsonl`（recall stats と同じ「expire 対象外・probe 入力」扱い）
- [ ] テスト: 各 type ヒント / secret 拒否 / 一時判定 / 共有範囲分岐

## 6. 承認

- [x] Agent B 承認（Issue #9 コメント 2026-07-06）
- [x] オーナー確定（draft → v1.0、2026-07-12 チャット GO）
