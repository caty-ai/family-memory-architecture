# FMA derived hero — reproducible image-generation brief

This file defines the FMA-specific derived hero for `assets/readme/hero.png`.
It inherits the frozen Family OS seven-node visual contract: same canvas ratio,
same fixed node positions, same palette, same labels, and optional dotted
connections only. If a local interpretation conflicts with the parent contract,
the parent contract wins.

## README Markdown

```md
![Family OSの全体地図。中央のFamily OSは地図と現在地を示し、周囲の6つの独立したタイルは、上から時計回りにFamily Dev Handbook（開発の約束）、FMA（共有記憶と観測）、Persona Growth Loop（将来の人格成長提案）、Self Growth Loop（改善提案と採用記録）、Sitter（見守り）、Caty Agent Harness（実行の継続）を表す。タイル間の点線の弧は、必須依存ではない任意の接続を表す。](assets/readme/hero.png)
```

## Output

- Create a `1600 × 900 px`, `16:9` PNG.
- Deliver an opaque dark-background raster with no transparency.
- Preserve all seven nodes, the fixed positions, and the frozen palette.
- This is a derived hero for the FMA repository, so only the FMA node may be
  emphasized.

## Prompt

> Create a calm, editorial product-diagram illustration for **FMA** inside the frozen **Family OS** seven-node map. Keep the same dark-navy canvas (`#0B1220`), slate tiles (`#182235`), ivory labels (`#F8FAFC`), subtle boundary, generous negative space, and top-down mission-table composition. This is a map, not a command center, not a dashboard, not a runtime controller, not a registry, and not a secret store.
>
> Use the authoritative anchors and labels exactly: **FAMILY OS** at the center `(800,450)` in sky (`#38BDF8`); **Family Dev Handbook** at `(800,140)` in amber (`#F59E0B`); **Caty Agent Harness** at `(360,295)` in violet (`#8B5CF6`); **FMA** at `(1240,295)` in teal (`#2DD4BF`); **Sitter** at `(360,605)` in rose (`#FB7185`); **Self Growth Loop** at `(800,760)` in lime (`#84CC16`); and **Persona Growth Loop** at `(1240,605)` in magenta (`#E879F9`). Generated centers may drift only within about `±40 px`. Do not move nodes to invent a new composition.
>
> Emphasize only the **FMA** node: give it a `2–4 px` outer ring, at most a `5%` scale increase, and the clearest local read on the canvas. Family OS remains visually central because it is the map entry point, never because it controls the other nodes.
>
> Suggest **horizontal memory flow** only inside or immediately around the FMA tile: depict a quiet left-to-right relationship among three compact memory/device cards inside the FMA node, with at most one or two tiny optional dotted hints local to that tile. Do not add new global arcs across the map for this emphasis. No arrows, no solid wires, no center-to-edge routing, no hub-and-spoke layout, no flowing particles, and no implication that any integration is required or already implemented.
>
> Give each node a simple distinct icon and a readable label. FMA should use three compact memory/device cards in a horizontal arrangement as its local motif, suggesting shared memory plus observation without becoming a file browser, code editor, or system console. Keep it geometric and quiet. Use a Japanese-capable clean sans-serif. Use exactly these seven labels and no others: `FAMILY OS`, `Family Dev Handbook`, `Caty Agent Harness`, `FMA`, `Sitter`, `Self Growth Loop`, and `Persona Growth Loop`.

## Negative prompt / exclusions

- Do not imitate Persona Engine's photography, celestial imagery, character art,
  emotional portrait framing, or chapter-cover style.
- No war room, mission control, cockpit, surveillance wall, operator chair,
  humanoid avatar, robot face, terminal grid, registry, installer, or command
  console.
- No arrows, mandatory pipes, ownership beams, nested containers, dependency
  chains, heartbeat graphs, progress badges, or success meters.
- No `PLANNED`, no status chip, no roadmap label, no explanatory sentence, no
  legend, no tiny annotation, no URL, and no extra text beyond the seven labels.
- Do not omit, merge, reorder, or relocate any of the seven nodes.

## Acceptance checklist

- [x] Output is exactly `1600 × 900 px`.
- [x] All seven nodes, labels, fixed positions, and palette assignments remain
  present.
- [x] FMA is emphasized only by the allowed derived-hero treatment: local ring
  and at most `5%` scale increase.
- [x] Family OS still reads as a map / current-location tile, not a controller.
- [x] Any arcs are dotted, sparse, optional, and non-directional.
- [x] The only meaningful raster text is the seven frozen node labels.
- [x] The README alt text names all seven nodes, their roles, and the fact that
  the dotted arcs are optional connections.
