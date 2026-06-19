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
- Pipeline **pauses** with `barcode_proposals.json` + `CONFIRM_BARCODES.md` until human sets `status: confirmed`
- Re-run with `--accept-proposals` to build annotation

**Test case:** hnRNPH GSE303135 / [GSM9118554](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSM9118554) — 15 bp barcode trim from GEO data_processing.

**Methods corpus:** [PMC6307142](https://pmc.ncbi.nlm.nih.gov/articles/PMC6307142/) iCLIP barcodes `NNNCGGANNN` / `NNNGGCANNN` (reference only; upload target is hnRNPH PMID 41867855).

## Next grilling question

**Q3:** For hnRNPH, is Flow `5' Barcode Sequence` **15N**, **30N** (barcode+UMI), or **16N** as in your current TSV? Confirm against FASTQ before upload.
