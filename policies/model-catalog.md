# model-catalog policy — 抽象サンプルカタログの運用規約（MoA v2.1 P1）

対象: `manifests/model-catalog.yaml`（+ `manifests/model-catalog.schema.json` / `manifests/member-state/`）。法= family-dev-handbook v0.11.0（L1-10 カタログ条項 / L1-11）。分界記録は、各 family agent foundry が私有面に置く boundary record を正とする。この公開版は抽象サンプルであり、実データは各 family の private surface に置く。

## 非規範宣言（handbook L1-10 と同文・逐語）

> **カタログは法が禁じる席を合法化できず、メンバーが生存確認できないモデルを使用可能にできない。eligibility はメンバー設定が勝ち、席数と制約はハンドブックが勝つ。**

- **G1**: カタログはパネルを名指ししない（5席 risk panel 等の名指し構成は各家の法・設定側）。
- **G2**: カタログは可用性フィールドを持たない（quota・liveness・verified_at・writer 被りはローカル or カーネルが選出時に計算する。共有された無日付の可用性主張は「信じられて、間違う」）。
- 規範力= **rebuttable default**: メンバーは理由記録つきで上書きできる。無記録の逸脱は非適合。

## 枠と選出

- 2枠制: `tier: priority`（S/M 既定の抽選母集団）/ `tier: substitute`（不足時の順次 fall-through）。枠内順序= `rank`（各 family の勢力図・時代で動く・`(tier, rank)` は一意）。
- `status: trial` の行は**抽選対象外・quorum 不算入**（`quorum_eligible: false` 必須・`recheck_after` 必須）。昇格はカタログ改訂で行う。
- **`status: retired` の行も抽選対象外**（`quorum_eligible: false` 必須 — 緊急降格 fast path を機械側でも即時に効かせる。行は監査のため残る）。
- **`quorum_eligible` はクラスレベルの family 共通事実**（trial/retired の quorum 不算入の機械化）であり、メンバーローカルの可用性 `eligible`（例: ローカル roster の `vendor-b-model-1` が `eligible:false`）とは別物 — 混同は G2 が防ぐ対象そのもの。
- 選出仕様（sha256 決定論 seed・filter→constrain→select・skip-log）は各メンバーのセレクタ実装側が持つ（本リポはデータのみ）。
- カタログ yaml は**制限 YAML プロファイル**で書く（anchors/tags/`---`/flow 集合/タブ不可・インデント 2/4/6・single-quote 内の `''` 不可 — 検査器が fail-closed で拒否する）。
- 公開サンプルの `vendor-c-model-1` と `vendor-c-model-2` は、同一 vendor 内の通常席と escalation-only 席を表す。`vendor-h-model-1` は `data_handling: training-contributor` の例であり、機微データには `standard` を使う。

## 使用時 stamp（fail-closed）

- 席決定時、メンバーのセレクタは自分の採用 `catalog_digest` を照合し、**現行改訂の `revision_effective_after` を超えて古い場合は fail-closed**（席決定を拒否）。
- 完了は公開された状態から導出する: ①`manifests/member-state/` の state record（member / catalog_digest_adopted / config_digest / referenced_ids / verified_at / spec・vectors versions）②実席決定に stamp された catalog_digest。誰も「done」と手で書かない。**ack は advisory** — 本リポの CI は、旧 digest の state record を `revision_effective_after` 以内なら**通知つきで通し**（採用遅れは設計上の正常状態）、期限超過のみ error にする（執行の本丸はメンバー側セレクタの使用時 fail-closed）。
- `config_digest` の定義= **そのメンバーのローカル席設定ファイルの生バイト sha256**。第三者はメンバーが公開した設定と突合して検証できる。
- `referenced_ids` の定義= **そのメンバーのローカル席設定ファイル（生バイトが `config_digest` になる同じファイル）が参照する model id の集合**。重複を除き、UTF-8 bytewise / Unicode codepoint の昇順（case-sensitive、locale 非依存。shell では `LC_ALL=C`）に固定する。case-fold / `str.lower` 順は禁止。同ファイルが変わるたびに機械的に再生成する。`config_digest` と `referenced_ids` の整合は構造上保証されず運用規律だけで保たれるため、必ず同時に更新する。
- JSON のローカル席設定（`seats[].model_id`）から state record へ貼る配列を生成する一行（`SEAT_CONFIG` は `config_digest` を取る同じファイル）:
  ```sh
  LC_ALL=C python3 -c 'import json,sys; d=json.load(open(sys.argv[1], encoding="utf-8")); print(json.dumps(sorted({seat["model_id"] for seat in d["seats"]}), ensure_ascii=False, separators=(",", ":")))' "$SEAT_CONFIG"
  ```
- 公開サンプル `member-a` の `config_digest` は `printf 'member-a-sample-config' | shasum -a 256` で導出する。
- 決定記録の catalog_digest が `revision_effective_after` を超えて古い場合は「遅延」でなく**非適合**として報告（報告主体は checker・P1 では上記 fail-closed が先に止める）。

## merge 権限（オーナー専決 + CI ゲート + front door + fast path）

- **merge は各 family のオーナー専決**（tier 構成・順序・status はコスト/能力/好みの判断= R-3 オーナー専決領域）。
- **family PR front door**: 提案は誰でも PR で出せる（merge はオーナーのみ）。
- **CI ゲート（fail-closed・`scripts/model-catalog-check`）— 実際に執行する項目**: schema 検証（3点一致の drift guard つき）/ 全行 lineage 宣言 / 重複 id・重複 (tier,rank) なし / trial・retired 行の quorum_eligible=false 強制 / 抽選可能行（current+priority+quorum_eligible）1行以上 / G2 sweep（ヘッダ含む全域）/ policy 逐語文+必須見出しの存在検査 / **改訂 bump 検査**（カタログ内容が変わったのに revision が増えていない PR は FAIL・baseline= `origin/main` の現行カタログ）/ changelog・blast_radius の存在 / member-state の schema+digest 窓検査 / member-state `referenced_ids` の必須・非空・重複なし・昇順検査と catalog id への union check（retired id の参照は通すが NOTICE）/ public-snapshot 除外節（本 policy の当該見出し）の存在検査。除外**ファイル**自体の存在検査は配布ゲート側の責務（下記 §public-snapshot 除外）。
- **理由つき N/A（ゲート一覧との差分・LC-1 つき）**: ①**メンバー側で never-blessed id の採用を拒否** — 本リポの公開面は各メンバーのローカル席設定と実行時 stamp を読めないため、その採用時拒否そのものは P1 では検査不能（各 family の private selector follow-up Issue・LC-1= 次の selector 改訂）。ただし、公開された state record の `referenced_ids` と catalog id の union check は上記 CI ゲートで強制し、未採用の旧 digest が adoption window 内にある場合だけ NOTICE とする。②**conformance vectors 通過** — vectors は法側で公開後に CI へ組み込む。
- **緊急降格 fast path**: 事由つき retire はオーナー directive+期限で即時（静かな reorder と区別）。retired 行は削除せず `status: retired` で残す（監査）。
- 同意の実体は **per-member pinned adoption**（handbook v0.11.0）: merge は誰のホストの既定も変えない。メンバーが adopt するまで動かない。

## public-snapshot 除外

private deployment が実名を含むカタログを持つ場合は public-snapshot 生成対象から**除外リストで明示的に外す**。配布ゲートで実名混入= FAIL。除外宣言の様式の正本: `policies/public-snapshot-exclusions.md`（宣言パターン — private deployment はこれを実リストとして具体化する）。配布ゲートへの除外検査の機械組み込みは各 family の private follow-up Issue とし、それまでは手動 runbook に除外手順を明記する。

- ゲートの執行形の注記: CI workflow は path-filter つきのため、branch protection の required check に据える場合は無関係 PR の pending 挙動をオーナーが設定時に確認する（手動 `workflow_dispatch` 起動も可能にしてある）。

## LC-1（退場トリガー）

| artifact | 退場 |
|---|---|
| カタログ行 | オーナー改訂（fast path 含む）・削除せず status=retired |
| trial 行 | `recheck_after` 到来で見直し |
| state record | 再公開で supersede（latest-wins・旧版は git 履歴）・メンバー退場/consumer 除外で retire |
| 本 policy | 分界の改訂（オーナー決裁）で supersede |
