# Flow Compile — design decisions (grilling session)

## Q1: Monolith vs chain?

**Decision:** Orchestrator chain. `flow-compile` coordinates stages; each stage has a clear owner.

| Stage | Owner | Notes |
|-------|-------|-------|
| 1. PubMed alert | `pubmed-summariser` via `lib/pubmed_stage.py` | Reuses `pubmed_api.fetch_papers`; no duplicate esearch |
| 2. GEO audit | `lib/geo_matrix.py` | Parse series matrix, GSM index |
| 3. Barcode resolve | `lib/barcode_resolver.py` | Protocol profiles: `flash`, `iclip2` |
| 4. Annotation build | `lib/flow_annotate.py` | Rules from annotation-file-creation skill |
| 5. Prefetch | `flow_compile.py` | `prefetch.sh` for HPC |
| 6. Upload | **External** `uploadsample_flowbio_v6.py` | Learn flow-ai *concepts* only; do not depend on flow-ai plugin |

## Organism rule

**Decision:** `Organism` column is **always** `Hs`, `Mm`, or `Gg`. Full scientific names (`Homo sapiens`) are rejected at validation. See `lib/organism.py`.

## flow-ai relationship

**Decision:** Read [goodwright/flow-skills flow-ai](https://github.com/goodwright/flow-skills/tree/main/plugins/flow-ai/skills/flow-ai) for API vocabulary (project/sample/upload). Implement upload through existing `flowbio.v2` Python client in advbfx, not through flow-ai's curl/CLI surface.

## Planned separate skills (future PRs)

- `clip-barcode-resolver` — extract when protocol profiles grow
- `flow-annotate` — shared with manual annotation workflows

## Q2: Agent vs Python for paper methods?

**Decision:** Agent-assisted extraction with human confirmation gate.

- Agent (or user) supplies paper methods + GEO sample text paths
- Python (`lib/barcode_evidence.py`) extracts candidate patterns deterministically
- `geo_matrix.py` scans matrix cells for literal `[ACGTN]+` barcode hints (`barcode_hints`)
- Pipeline **pauses** with `barcode_proposals.json` + `CONFIRM_BARCODES.md` until human sets `status: confirmed`
- Re-run with `--accept-proposals` to build annotation
- Empty evidence → `NEEDS_USER_INPUT`; agent must not invent patterns

**Search order (grilling audit, 2026-07):** gather evidence from **all** sources (matrix → GEO pages → paper → referenced papers → ENA SDRF), rank by `kind`, present full evidence table, hard stop until confirmed.

### Q3 — partial evidence / sibling N-pattern (grilling 2026-07-08)

**Decision:** Do not block the whole study when most GSMs resolve and one lacks direct evidence.

- Allow compile through annotation/download for resolved GSMs.
- For unresolved GSMs: **agent responsibility only** — agent may propose an N-only pattern matching sibling length in `barcode_proposals.json` with clear `agent_notes` before user confirmation. **No automatic Python inference** in `barcode_extract.py`.
- Still **pause at barcode confirmation**; user must explicitly confirm every GSM.

### Q4 — paper barcodes vs matrix filename cores (grilling 2026-07-08)

**Decision:** When the paper lists multiple demux barcodes and a GEO supplementary filename embeds a short fixed core (e.g. `_rsem_CGGA.` / `_rsem_GGCA.`), treat that as **replicate-specific variant assignment**, not a contradiction.

- **GSE105082 example:** Methods give `NNNCGGANNN` and `NNNGGCANNN`. GSM2817677 supp file has `CGGA` → rep1 variant `NNNCGGANNN`; GSM2817678 has `GGCA` → rep2 variant `NNNGGCANNN`.
- Agent presents **both** the paper quote and the filename core in `CONFIRM_BARCODES.md`, with a short explanation linking core → full pattern.
- **No automatic CONFLICT flag in Python** — agent reads the evidence table and writes `agent_notes` (same as Q3: agent compares sources).
- Status stays `pending_confirmation` until the user confirms each GSM.

### Q5 — hnRNPH-style: bp-length evidence, no literal motif (grilling 2026-07-08)

**Case:** GSM9118554 (hnRNPH iCLIP2, GSE303135) — GEO *Data processing* gives lengths, not a motif: "Barcode trimming (first 15 bp...)" and "min. read length of 30 bp includes 15 bp barcode and UMI regions plus 15 bp sequence insert."

**Question:** Is `5' Barcode Sequence` **15N**, a combined **30N**, or something else?

**Decision:** Correct answer is **15N**. The agent's responsibility is to:
1. Quote the GEO Data processing evidence exactly (both the trim sentence and the min-read sentence).
2. Make an **attempted guess**, not just list raw options — propose 15N based on the reasoning that GEO describes "15 bp barcode **and** UMI regions" as separate quantities within a 30 bp total, and that a 30N combined run would be unusually long for a single 5' barcode field.
3. Explicitly flag that this guess relies on **general protocol knowledge** (typical barcode/UMI lengths), not something derivable purely from the quoted text, and — critically — **is not verifiable from the FASTQ itself**. Barcode and UMI are both random bases with no visible boundary in the read, so inspecting reads cannot confirm the split. (This corrects an earlier draft of this doc that suggested "confirm against FASTQ" — that check doesn't work for random-base barcodes.)
4. Still present the guess in `CONFIRM_BARCODES.md` for explicit user confirmation — never silently commit to 15N without the hard stop.

This generalizes: whenever evidence gives **lengths only** (no literal `[ACGTN]` string), the agent must reason from bp counts to a proposed N-pattern and clearly label that reasoning as an inference, distinct from literal-motif evidence (e.g. GSE105082's `NNNCGGANNN`).