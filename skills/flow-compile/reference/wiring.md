# Wiring — stages, library modules, vendored scripts

The stage pipeline with each stage's library toolkit attached. Solid arrows are the run
order; dotted lines attach the `lib/` modules a stage imports (read from each stage's
`from lib.…` imports — regenerate this diagram from those, not from memory). Hexagons are
the three hard stops.

`110_import` imports no library beyond the stage contract: it shells out to the `flowbio`
CLI. Every stage runs inside `run_stage()` from `stages/_common.py`,
which owns prerequisites, input digests, and the exit codes documented in
`reference/stages.md`.

```mermaid
flowchart TD
    S00["00_setup"]:::stage --> S01["01_study"]:::stage --> S02["02_index"]:::stage --> S03{{"03_barcodes · GATE 1"}}:::gate
    S03 --> S04["04_annotate"]:::stage --> S05{{"05_metadata · GATE 2"}}:::gate --> S06{"06_route"}:::stage
    S06 -->|"in SRA/ENA"| S101["101_preview"]:::stage
    S06 -->|"not in SRA"| S201["201_fetch"]:::stage
    S101 --> S108{{"108_params · GATE 3"}}:::gate
    S201 --> S108
    S108 --> S109["109_sheet"]:::stage --> S110["110_import"]:::stage --> S11["11_verify"]:::stage
    S108 --> S210["210_upload"]:::stage --> S11
    S11 --> S12["12_analysis"]:::stage --> S13["13_audit"]:::stage

    L00["flow_client · credentials"]:::lib -.- S00
    L01["study_check · import_guards"]:::lib -.- S01
    L02["geo_matrix · flow_annotate"]:::lib -.- S02
    L03["barcode_extract · barcode_evidence<br/>read_structure · geo_matrix"]:::lib -.- S03
    L04["flow_annotate · geo_matrix · barcode_resolver<br/>paper_metadata_enrich · protocol"]:::lib -.- S04
    L05["metadata_validate"]:::lib -.- S05
    L06["protocol"]:::lib -.- S06
    L101["sra_header_preview · header_state"]:::lib -.- S101
    L201["header_state"]:::lib -.- S201
    L108["header_state · pipeline_params<br/>read_structure · import_guards"]:::lib -.- S108
    L109["sra_import · import_guards"]:::lib -.- S109
    E110(["flowbio CLI — samples import"]):::ext -.- S110
    L210["import_guards"]:::lib -.- S210
    L11["import_check · flow_client"]:::lib -.- S11
    L12["flow_stages · pipeline_params<br/>reference_cross_check"]:::lib -.- S12
    L13["execution_audit"]:::lib -.- S13

    classDef stage fill:#0e7369,stroke:#0e7369,color:#ffffff,font-weight:600;
    classDef gate fill:#b45309,stroke:#b45309,color:#ffffff,font-weight:600;
    classDef lib fill:#52606d,stroke:#52606d,color:#ffffff,font-size:11px;
    classDef ext fill:transparent,stroke:#7c8c87,stroke-dasharray:4 3,color:#7c8c87,font-size:11px;
```

## The vendored layer, in one line each

Nine scripts under `lib/vendor/` (patches indexed in `lib/vendor/README.md`), reached three ways:

| reached by | scripts |
|---|---|
| imported (the only one) | `parse_key_resources_antibodies.py` — antibody formatting for `metadata_validate` and `paper_metadata_enrich` |
| wrapped by generated runners | `flowrunanalysis_flowbio.py` (runner written by `12_analysis`), `uploadsample_flowbio_v6.py` (via `flow_stages.write_upload_script`) |
| standalone, manual operations | `flow_edit_samples.py`, `flow_public_samples_pull_v3.py`, `flow_public_samples_push_metadata_v2.py`, `pull_project_metadata.py`, `apply_metadata_proposals.py` — `11_verify`'s automated repair goes through `lib/flow_client` instead |

`removespace.py` is vendored but superseded locally: header cleaning runs inside the
clip-seq pipeline on Flow.
