# public-snapshot 除外宣言パターン

private deployment が実名モデルデータを置く場合に、public-snapshot / 公開スナップショット生成の対象から**除外する**パスの宣言パターン。配布ゲートは deployment の宣言を読み、除外対象の内容（実名モデル ID 等）が snapshot に混入していたら **FAIL** する（fail-closed）。抽象 ID だけの公開サンプルには、実名混入を理由とする除外は不要。

| パス | 理由 | 追加日 |
|---|---|---|
| `manifests/model-catalog.yaml` | private deployment で実名を含む場合: 実名モデルカタログ（実名はデータ層・私有面） | 2026-08-15 |
| `manifests/model-catalog.schema.json` | private deployment の schema が例示値に実名を含む場合 | 2026-08-15 |
| `manifests/member-state/` | private deployment で実メンバーの採用状態（digest・設定指紋）を含む場合 | 2026-08-15 |
| `policies/model-catalog.md` | private deployment の規約が実名・実枠順を含む場合 | 2026-08-15 |

- 機械組み込みは各 family の private follow-up Issue とし、最初の snapshot 生成前までに行う。それまでは配布 runbook の手動手順にこの宣言パターンを反映する。
- 行の削除は各 family のオーナー専決（除外解除= 公開判断）。
