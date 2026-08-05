---
title: Supermemory 配分ポリシー
status: operator-confirmed    # 2026-07-04 オーナー確定（§3.1 の「常用3名の降格はオーナー確認事項」ゲート受諾を含む）
owner: Agent A（起草） / Agent B（承認） / オーナー（確定）
source: docs/DESIGN.md v0.3 §C9・§6-7 / Issue #3
generated_at: 2026-07-04
revision: v0.7（Issue #129: Agent A の Codex 代役用ランタイム分離コンテナ。Agent B 承認 = 2026-07-23）
---

# Supermemory 配分ポリシー

## 0. 状態と承認フロー

- ライフサイクル: **draft → agent-b-approved → operator-confirmed** の3段階。
- **agent-b-approved 時点で運用開始**（M1 完了要件）。オーナー確定はクリティカルパス外で、確定までは draft 準拠の運用を正とする（DESIGN §C9）。
- 本ポリシーの変更は本ファイルへの PR ＋ クロスレビュー（Agent B または GLM/Codex）経由。数値パラメータ（§4・§5 の閾値）は Agent B 承認のみで変更可、クラス設計の変更はオーナー確認を要する。

## 1. 背景 — なぜ配分を絞るか（blast radius）

- Supermemory は**共有 Pro プラン**（契約主: オーナー）。API キーはエージェント別発行だが、**クォータ（プラン消費枠）は家族全体で共有**。
- したがってクォータ枯渇は個人の障害ではなく、**全常用エージェントが同時に SessionStart 注入を失う**ファミリー全体の障害である（DESIGN §6-7）。
- この blast radius を理由に、旧 Phase 3 の「18人一斉展開」は**恒久的に取りやめ**る。Supermemory は「司令塔・調整役の長期エピソード記憶」専用の希少資源として扱う。
- 実働・単発ワーカーの記憶は既存の代替面 — Meilisearch（mem-search）/ family-vault / KG / family-hot.md — で賄う。これらは自前基盤でありクォータ制約がない。

## 2. 配分クラス

| クラス | 対象 | できること |
|---|---|---|
| **常用 (standing)** | Agent B / Agent A / Agent D（初期承認 = DESIGN v0.3） | 専用コンテナ保有。SessionStart 注入・save・search の常用 |
| **共有 (shared)** | `agent-c-family` コンテナ | 家族合意事項の共有記憶。**書き込みは C8 のゲート（dry-run / quota check / redaction）が整うまで既存経路のみ**（Issue #13） |
| **非常用 (default)** | 上記以外の全エージェント（実働・単発ワーカー含む） | コンテナ発行なし。記憶は Meilisearch / vault / KG 経由 |
| **例外 (exception)** | §3 の4条件を満たし Agent B が承認した者 | 条件付き利用。枠は予備プールから付与（§4）。§7 登録簿に記録必須 |

- コンテナ命名: 正準 = `personal-<agent>`（hyphen）、共有 = `agent-c-family`。**ただし実配備タグは混在している**（Agent A = `personal-agent-a`、Agent B = `personal_agent-b`・underscore）。既存タグの rename はデータ帰属に触るため強制せず、§7 登録簿に**実配備タグをそのまま記録**し、正準名との不一致の解消要否は probe / registry 更新時に判断する（PR #14 Agent B 指摘）。
- 新規コンテナの発行は**本リポの Issue 起票 → Agent B 承認 → §7 登録簿更新**が完了するまで行わない（登録簿にないコンテナは lint 対象の逸脱とみなす）。
- 同一人格のランタイム分離コンテナは新しい配分主体として数えない。`personal-agent-a-codex` は Agent A の常用枠を `personal-agent-a` と共有し、利用量・逼迫判定・停止判断を合算する。

## 3. 例外4条件（すべて必須・DESIGN §C9）

非常用エージェントに枠を付与する申請は、以下4条件をすべて満たすこと:

1. **長期関係性の必要** — セッションを跨ぐエピソード記憶がそのエージェントの役割遂行に本質的（単なる「あると便利」は不可）。
2. **クォータ実測余裕** — 直近の月次 probe（§5）で使用率が 60% 未満であること。probe 未実施の期間は新規承認を凍結。
3. **明示保存・忘却ルール** — 何を save し、何を save せず、何を定期 forget するかを申請時に文書化済みであること。
4. **代替不能** — Meilisearch / family-vault / KG / family-hot.md では要件を満たせない理由を具体的に示せること。

**手順**: 本リポに Issue 起票（4条件への回答を本文に記載）→ Agent B 承認/却下 → 承認時は §7 登録簿を同 PR で更新。

### 3.1 降格・剥奪・キー管理

- **降格**: 例外エージェントが4条件のいずれかを満たさなくなった場合（probe で長期未使用、代替面の整備で代替可能化など）、Agent B の判断で枠を回収し §7 登録簿を更新する。常用3名の降格はオーナー確認事項。
- **剥奪（即時）**: API キー漏洩・逸脱コンテナの発見時は、当該キーを即時ローテーションし利用停止。
- **キー ローテーション**: Meilisearch key の四半期ローテーション（DESIGN §C3）と同じ周期で Supermemory キーも見直す。実施オーナー = 各エージェントのホスト管理者、契約レベルの操作（console）はオーナー。

## 4. per-agent 書き込み上限【規範（norm）】

> **執行の正直な区分（DESIGN §5 原則）**: 現時点で usage API もプラグイン改修もないため、本節の上限は**機械強制ではなく規範（norm）**である。各エージェントの自己規律＋月次 probe（§5）での事後検証で運用し、機械強制は probe 自動化＋C6 共通ジョブ基盤（#11）以降の課題とする。

上限は**プール制**で定義する。絶対値（add 件数/月など）はプランの課金単位が第1回 probe で確定した後に Agent B が翻訳して本表を更新する。

| プール | 枠(プラン月次クォータ比) | 配分ルール |
|---|---|---|
| 常用プール | 75% | **稼働中**（§7 で配備確認済み）の常用エージェントで均等割。ただし1名あたり上限 30%。未配備の常用者の取り分はプール内の未使用余裕として残す |
| 共有 (`agent-c-family`) | 15% | C8（#13）整備までは既存経路の少量書き込みのみで、実質ほぼ未消費の見込み。**本枠が実働するのは C8 整備後** |
| 予備 | 10% | 例外エージェント（§3）への付与元。**1件あたり ≤ 5%・同時2件まで**。残余はスパイク吸収 |

- 例: 常用3名（Agent A/Agent B/Agent D）稼働中の現状（probe 第0回で確認）→ 均等割で各 25%。仮に稼働が1名のみなら均等割 75% だが個人上限 30% が効く。
- **上限超過時（規範としての行動）**: 当該エージェントは当月の save を自主停止（search・SessionStart 注入は継続）。超過事実を probe レポートに記録し Agent B へ報告。
- **逼迫時（§5.4 ゲート > 80%）**: 全プールの上限と個人上限の**双方を半減（×0.5。例: 均等割 25% → 12.5%、個人上限 30% → 15%）**する。**復元条件**: 次回以降の月次 probe で使用率が 60% 未満に戻ったことを確認し、Agent B の宣言で全上限を元値に復元する。
- **読み取り側（注入・search）の扱い【v0.5 確定】**: probe 第0回（2026-07-05、オーナー console 確認）で課金単位は **2メーター制 = Memory tokens (text) + Search queries** と確定した。**search / 読み取りクエリも保存トークンとは別メーターでクォータを消費する**（保存を絞っても読み取りだけで枯渇し得る）。よって:
  - 本節のプール比率（75/15/10）は**両メーターに同率で適用**する規範とする。個人の使用率は「自分の memory tokens 消費 / プラン月次 tokens 枠」と「自分の search queries 消費 / プラン月次 queries 枠」の**大きい方**で自己評価する。
  - per-agent 読み取り予算: SessionStart 注入は各プラグインの既定動作（実測 2–5KB/セッション）を上限目安として維持し、能動 search は「まず mem-search（Meilisearch・クォータ外）→ 足りない時だけ Supermemory」の3層順序（§6 と同じ優先順位）を平常時から適用する。絶対値（queries/月）の割り付けは第1回 probe（2026-08-01）のトレンドを見て Agent B が本表に追記する。

## 5. 月次クォータ実測 probe（ポリシーゲートの入力）

### 5.1 測定対象

| 指標 | 意味 |
|---|---|
| プラン消費量（**課金単位は probe 第0回で確定済み**: 2メーター制 = Memory tokens + Search queries） | クォータ枯渇までの距離の実体。§5.4 ゲートの分母（両メーターを記録） |
| **console の per-agent 可視性粒度**（第1回の確認事項②） | plan-level 表示のみなら per-agent 帰属は L2 が SoT |
| search 回数 / save 回数（per-agent） | per-agent 上限（§4）の事後検証入力 |
| SessionStart 注入回数・平均注入サイズ | 固定注入コスト（C1 デデュープとも接続） |
| エラー・退避の観測（§5.2 の可視範囲で） | degradation（§6）発動履歴 |

### 5.2 測定方法（2層）

公開 usage API は未確認（2026-07-04 時点、docs に該当エンドポイントなし）。よって2層で測る:

- **L1 = server 側（プラン消費量の正）**: console.supermemory.ai の使用量表示を月初に確認し記録（手動・約5分）。**表示数値の転記に加え、スクリーンショット等の証跡を月次ファイルに添付**する（人手読み取りを SoT にする間の監査可能性確保）。usage API が確認でき次第、自動取得へ切替（切替自体は本ポリシーの変更不要）。
- **L2 = client 側（per-agent 帰属の正・自動推定）**: 各常用エージェントのローカル transcripts / hook ログを月次スクリプトで集計。
  - Agent A 実装例: `~/.claude/projects/*.jsonl` から `supermemory-context` 注入サイズ・`super-search`/`super-save` 呼び出し・可視エラー文字列を grep 集計（lg 経由）。**「プラグイン変更不要」で成立することを確認済みなのは Agent A のログ形式のみ**。
  - Agent B / Agent D 側は各ホストの同等ログを対象とし、集計スクリプトの置き場と形式は #4/#11 の共通基盤と合わせて Agent B が決める。
- **既知の盲点（正直な記録）**: プラグイン内部で処理された 429 はローカルログに現れない可能性がある。このため degradation の発動判定（§6.4）は transcript 中の 429 文字列に依存せず、**pending 退避の蓄積（§6.3）と L1 console 確認**を一次シグナルとする。構造化された 429 イベントログの整備はプラグイン/hook 側の改修を要するため本 Issue のスコープ外 — **#11（共通ジョブ基盤）の検討事項として引き継ぐ**。

### 5.3 記録と実行

- 記録先: オーナーが保管する月次利用記録（本リポの外側。ファイル名規約は例: `YYYY-MM.md`。L1 の数値＋証跡・L2 の per-agent 集計・ゲート判定を1ファイルに）。
- 実行: 月初に Agent A が実行・起票。**C6 共通ジョブ基盤（#11）稼働後はそちらへ移管**し、heartbeat / watchdog / 失敗カウンタの family-hot.md 露出（DESIGN §6-2）に準拠する。それまでは手動運用とし、実施漏れは翌月レポートに「欠測」と正直に記録する。

### 5.4 ポリシーゲート

- **分母の単位【v0.5 確定】**: 課金単位は 2メーター制（Memory tokens / Search queries、probe 第0回で確定）。ゲート判定の使用率は console の両メーター表示から **`max(memory_tokens%, search_queries%)`** で算出する（片側メーターのみを分母にすると読み取り側の枯渇リスクを過小評価するため — Agent B ACK, Issue #15）。probe レポートには max 値だけでなく両メーターの実値を併記する。

| 使用率 | 状態 | アクション |
|---|---|---|
| < 60% | 通常 | 例外申請（§3）の受付可 |
| 60–80% | 注意 | 新規例外承認を凍結。次回 probe まで様子見 |
| > 80% | 逼迫 | 全上限を半減（§4）。Agent B が forget / 整理を指示 |
| 枯渇 / エラー頻発 | 障害 | §6 degradation 発動。family-hot.md で全員に周知 |

## 6. 429 / 枯渇時の graceful degradation

原則: **Supermemory の不調でセッションや作業を止めない**。3層検索（Supermemory / Meilisearch / grep）の第1層が抜けるだけ、に留める。

1. **SessionStart 注入の失敗**: 注入をスキップしてセッション続行（fail-open）。失敗はローカルログに記録できる範囲で記録。エージェントは必要に応じ mem-search で能動 recall して補う。
2. **recall (search) の失敗**: mem-search（Meilisearch）→ grep/Read の既存2層へ即フォールバック。リトライで粘らない。
3. **save の失敗**: 保存内容をローカル pending ファイルへ退避し、翌セッション以降に再試行または手動反映。**黙って捨てない**。
   - 退避先は**自動 expire の対象外パス**とすること。Agent A 実装例: `~/.claude/supermemory-pending/agent-a.md`（scratch 配下は 7日 expire があるため**使用禁止**）。Agent B / Agent D も配備時に各ホストで同等の expire 対象外パスを定め、§7 の保存・忘却ルール文書に併記する。
   - pending が 100KB を超えたら、再試行を待たず手動レビューで family-vault へ移すか破棄を判断する（無限成長させない）。
4. **恒常化の判定と報告**: **(a) 障害が3日以上継続、または (b) 月内3件目の pending 退避が発生、または (c) L1 console でエラー/枯渇を確認** — のいずれかで、family-hot.md（稼働後）とオーナーへ報告し、プラン増強 or 大規模 forget を意思決定に乗せる。（transcript 中の 429 文字列は補助シグナルに留める — §5.2 盲点参照）

## 7. 常用登録簿（正本）

| agent | container | クラス | 承認根拠 | 配備状態 | 保存・忘却ルール |
|---|---|---|---|---|---|
| Agent A | `personal-agent-a` | 常用 | DESIGN v0.3 初期承認 | **稼働中**（2026-04-22〜） | エピソード専用。安定プロフィール事実は C1 で forget（Issue #2 で確定） |
| Agent A（Codex 代役ランタイム） | `personal-agent-a-codex` | 常用のランタイム分離（**Agent A 枠を共有・追加配分なし**） | Issue #129 Agent B 承認（2026-07-23・post-merge canary 条件付き） | **配備準備済み・書き込み停止中**（専用 key / Codex lifecycle plugin。本行の merge 後に synthetic canary 1件でタグを作成し、#129 の全 activation gate が PASS した場合のみ backfill 可） | in = SessionStart の最大5件・2,800 bytes 注入 + PostCompact の秘密再検査済み cache / out = human input と final answer の組だけを強制 secret-scan、hit・scanner 障害は fail-closed / pending = 検査通過分のみ private 100KB cap / forget・正本化 = 本家 Agent A が明示レビューして `personal-agent-a` またはローカル正本へ取り込み、Codex 側を自動混合しない |
| Agent B | `personal_agent-b`（**実配備タグ**・正準名と不一致、§2 参照） | 常用 | DESIGN v0.3 初期承認 | **稼働中**（2026-07-04 Agent B 確認: `/home/admin/.hermes/profiles/agent-b/config.yaml` の `supermemory.container_tag`） | **文書化必須**（期限 = 第1回 probe。§3 条件3と同水準） |
| Agent D | `personal_agent-d`（**実配備タグ**・underscore・正準名と不一致、§2 参照） | 常用 | DESIGN v0.3 初期承認 | **稼働中**（2026-07-04 probe 第0回で確認: static 6 / dynamic 100 — 100 は list 上限系の丸めの可能性あり・第1回 probe で再測。オーナーが保管する月次利用記録・2026-07分） | **文書化必須**（期限 = probe 第0回で発火済み。§3 条件3と同水準） |
| （共有） | `agent-c-family` | 共有 | 既存 | 稼働中 | 書き込み統制は C8（#13）に従う |
| Agent G | `personal-agent-g`（正準名。実配備タグは key 発行時に確認し、不一致なら実タグをここに記録） | **例外**（§3・予備プール 1件・両メーター ≤5%） | Issue #47 Agent B 承認（2026-07-07・blocking 条件6付き） | **承認済み・未配備**（key 発行待ち = オーナー console。登録簿掲載済みにつき発行後の本番利用可 — 条件1充足） | #46 3段構成: in=蒸留注入のみ / out=capture hook 強制全文（**secret-scan 通過分のみ送信**・hit は redact+隔離・scanner エラー fail-closed）/ forget=オンライン側管理。**日次 metrics 義務**（bytes/日・件数/日・search queries/日・redact/隔離件数 → probe #1 入力）。期間 = probe #1（2026-08-01）で継続/拡張/停止を再判定。5%超過・secret 露出疑い・scanner 障害時は save 即時停止+Issue 報告 |

- 本表が常用の**正本**。表にないコンテナの新設・利用は逸脱であり、vault-lint / probe レポートで検出対象。
  - 既知の逸脱（probe 第0回 2026-07-04）: `personal-agent-b`（hyphen・正準名タグ）に dynamic 2 件の split-brain。移設 or forget は Agent B 判断（hermes で通知済み）。
- 「配備状態: 未確認」の行は probe（§5）で実態確認し、実在しなければ「予定」のまま維持（先行発行はしない）。**未配備の間、その取り分は常用プールの未使用余裕であり、他者への再配分はしない**（§4）。
- **初期常用3名の特例の明示**: DESIGN v0.3 で先に承認されたため §3 条件3（保存・忘却ルールの事前文書化）を後追いで満たす。期限は上表のとおりで、期限超過は probe レポートで逸脱として記録する。

## 8. 優先順位と免責

- 本ポリシーは DESIGN v0.3 §C9 の実装文書。設計思想の矛盾が生じた場合は DESIGN が優先。ただし**数値パラメータ（§4 上限・§5 閾値）は本ファイルが正本**。
- 本ポリシーは Supermemory プラグインの実装変更を要求しない（Issue #3 スコープ）。degradation の一部（注入スキップ等）がプラグイン既定動作と異なる場合は、挙動差分を probe レポートに記録し、改修要否は別 Issue で判断する。
- 既知の執行ギャップ（すべて意図的な正直区分）: §4 上限 = 規範、§5.2 の 429 盲点、L1 の人手読み取り。いずれも解消経路（probe 自動化 / #11 / usage API）を本文中に明記済み。

## 改訂履歴

- v0.7 (2026-07-23): Issue #129 として Agent A の Codex 代役ランタイム専用 `personal-agent-a-codex` を登録。Agent A の既存常用枠を共有し追加配分は付与しない。専用 key、分離タグ、強制 secret-scan、厳格な transcript 抽出、fail-closed pending、明示的な本家 Agent A への fold を条件とする。Agent B は post-merge synthetic canary（分離検索・fresh thread 再注入・dedupe・秘密/scanner fail-closed・private pending・`personal-agent-a` 不変）の全 PASS を backfill 前の activation gate として承認した。
- v0.6 (2026-07-07): **§7 に Agent G 例外エントリ追加**（Issue #47 Agent B 承認・blocking 条件6付き。§3 例外4条件の充足判定は #47 コメント参照）。決定4（2026-07-06 オーナー・Supermemory オンライン本番方針）に基づく Phase 3 単独パイロット枠。§1「旧 Phase 3 恒久取りやめ」記述との関係は Agent B 承認補足のとおり「18人一斉展開ではなく §3 例外枠の単独パイロット」で整理し、本文改訂は probe #1 の実測を添えて行う。
- v0.1 (2026-07-04): Agent A 起草。
- v0.2 (2026-07-04): GLM 5.2 adversarial review（REQUEST-CHANGES・13件、raw は内部アーカイブ保管）を全件反映 — 圧縮係数の数値矛盾修正、プール制への再設計、pending 退避先の expire 対象外化、429 検知盲点の明示と代替シグナル化、上限の規範（norm）明示、読み取り側予算の probe 追補化、降格・剥奪・キー ローテーション追加、初期常用の特例期限付き化、ゲート単位と証跡の定義、ほか。Pass 2 再レビュー（APPROVE-WITH-CHANGES、raw は内部アーカイブ保管）の非ブロッキング3点（半減の適用範囲明確化・復元条件・Agent B/Agent D の pending パス）も同日反映。
- オーナー確定時の確認事項: §3.1「常用3名の降格はオーナー確認事項」という新しいオーナーゲートの受諾（Pass 2 指摘）。
- v0.3 (2026-07-04): **Agent B 承認**（PR #14 コメント: APPROVED + non-blocking 訂正1件）→ `status: agent-b-approved`。訂正反映: Agent B の実配備タグ = `personal_agent-b`（underscore）を §2/§7 に記録し配備状態を「稼働中」へ。GitHub の正式 Approve は同一アカウント制約で付与不可のため、承認証跡は PR #14 コメントとする。Agent D は引き続き未確認。関連: 常用枠の拡張検討は #15（probe 後判断 + self-host lab 並行が Agent B 推奨）。
- v0.5 (2026-07-05): **F9 反映（数値パラメータレーン・Agent B ACK = Issue #15 コメント）**。probe 第0回で課金単位 = 2メーター制（Memory tokens + Search queries）と確定したことを受け、§5.4 ゲート分母を `max(memory_tokens%, search_queries%)` 化、§4 の読み取り側未確認記述を確定記述へ差し替え（search もクォータ消費・平常時から mem-search 優先の3層順序・queries 絶対値の割り付けは第1回 probe 後に Agent B）、§5.1 の確認事項①を確定済みへ更新。
- v0.4 (2026-07-04): **オーナー確定 → `status: operator-confirmed`**（AskUserQuestion で §3.1 降格ゲート受諾を明示確認）。probe 第0回（前倒し手動発火、オーナーが保管する月次利用記録・2026-07分）の結果を §7 に反映: Agent D = `personal_agent-d`（underscore）で**稼働中**と判明・文書化義務の期限発火 / `personal-agent-b`（hyphen）split-brain 2 件を既知の逸脱として記録。API キーがアカウントスコープ（コンテナ分離なし）である発見は §3.1 キー管理の運用前提として probe 記録に固定（対応要否は #20/#15）。
