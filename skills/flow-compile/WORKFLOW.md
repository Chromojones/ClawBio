# flow-compile — end-to-end workflow

Paste the diagram below into any Mermaid renderer (GitHub, Notion, mermaid.live, etc.).

**Legend**

| Label | Meaning |
|-------|---------|
| **manual** | Agent hook — pause for user/agent confirmation (barcodes, params, Flow project) |
| **agent** | Agentic — Cursor agent dispatches skills, reads literature/GEO, proposes barcodes |
| **script** | Scripted — deterministic Python (`flow_compile.py` / `lib/*`) or generated shell + 4-min polling |

```mermaid
flowchart TD
    subgraph legend[" "]
        direction LR
        LG1[manual]:::manual
        LG2[agent]:::agent
        LG3[script]:::script
    end

    subgraph manual_gates["Agent hooks"]
        M1["Create Flow project<br/><i>hook</i>"]:::manual
        M2["Barcode hook<br/>CONFIRM_BARCODES.md<br/><i>hook</i>"]:::manual
        M3["Analysis params hook<br/>CONFIRM_ANALYSIS_PARAMS.md<br/><i>hook</i>"]:::manual
        M1 --> M2 --> M3
    end

    subgraph start["0 · Credentials"]
        M3 --> C0["Prompt Flow username/password<br/><i>script</i>"]:::script
        C0 --> C1["Write .flow_credentials.env<br/><i>script</i>"]:::script
    end

    subgraph discover["1 · Literature & GEO"]
        C1 --> B["pubmed-summariser<br/><i>agent</i>"]:::agent
        B --> C["geo-matrix parse<br/><i>script</i>"]:::script
        C --> D["barcode-extract<br/><i>agent</i>"]:::agent
        D --> E{"barcode hook<br/>confirmed?<br/><i>hook</i>"}:::manual
        E -->|pause| E
        E -->|yes| F["flow-annotate<br/><i>script</i>"]:::script
    end

    subgraph local["2 · Local FASTQ prep (poll every 4 min)"]
        F --> G["prefetch.sh<br/><i>script</i>"]:::script
        G --> G2{"download finished?<br/><i>script</i>"}:::script
        G2 -->|poll| G2
        G2 -->|yes| H["headers.txt + pipeline_params.json<br/><i>script</i>"]:::script
        H --> I{"needs removespace?<br/><i>script</i>"}:::script
        I -->|yes| J["clean_fastq.sh<br/><i>script</i>"]:::script
        I -->|no| L
        J --> J2{"clean finished?<br/><i>script</i>"}:::script
        J2 -->|poll| J2
        J2 --> L["*.cleaned.fastq.gz<br/><i>script</i>"]:::script
    end

    subgraph deliver["3 · Flow delivery (poll every 4 min)"]
        L --> N["annotation.csv<br/><i>script</i>"]:::script
        N --> P["upload_live.sh<br/><i>script</i>"]:::script
        P --> P2{"upload finished?<br/><i>script</i>"}:::script
        P2 -->|poll| P2
        P2 --> Q["run_analysis.sh<br/><i>script</i>"]:::script
        Q --> Q2{"analysis finished?<br/><i>script</i>"}:::script
        Q2 -->|poll| Q2
        Q2 --> U["CLIP-Seq execution on Flow<br/><i>Flow platform</i>"]:::platform
    end

    classDef manual fill:#fff3cd,stroke:#856404,color:#333
    classDef agent fill:#d1ecf1,stroke:#0c5460,color:#333
    classDef script fill:#d4edda,stroke:#155724,color:#333
    classDef platform fill:#e2e3e5,stroke:#6c757d,color:#333
```

## Agent vs script boundary

| Phase | Who drives it | What runs |
|-------|---------------|-----------|
| Literature → barcodes | **Agent** | Invokes `flow_compile.py`; dispatches `pubmed-summariser`; reads GEO/paper text for `barcode-extract` proposals |
| Barcode/project/analysis hooks | **Agent + you** | `CONFIRM_BARCODES.md` (with sources), `CONFIRM_ANALYSIS_PARAMS.md`, Flow project ID |
| Compile artifacts | **Script** | `lib/geo_matrix`, `lib/flow_annotate`, `lib/fastq_headers`, `lib/flow_stages` → JSON/XLSX/shell scripts |
| Long-running steps | **Script** | `prefetch.sh`, `clean_fastq.sh`, `upload_live.sh`, `run_analysis.sh`; polled every 4 min by `--run-automated` |

The agent presents hook artifacts and pauses for confirmation. After `--accept-proposals`, long-running execution is scripted, with the analysis-params hook before submission.

## Agent hooks

1. **Barcode hook** — agent presents `CONFIRM_BARCODES.md` (includes evidence **source** and quote); user confirms in `barcode_proposals.json` → `--accept-proposals`
2. **Flow project** — create project in Flow UI; pass `--flow-project-id`
3. **Analysis params hook** — agent presents `CONFIRM_ANALYSIS_PARAMS.md`; after review, copy to `analysis_params.confirmed.json`:

```bash
cp /tmp/gse105082-prefetch/pipeline_params.json \
   /tmp/gse105082-prefetch/analysis_params.confirmed.json
```

## Automated run (credentials first, 4-min polling)

```bash
uv run python skills/flow-compile/flow_compile.py \
  --case gse105082 \
  --output /tmp/gse105082-prefetch \
  --accept-proposals barcode_proposals.json \
  --fastq-dir ~/gse105082/fastq_files/fastq_files \
  --run-automated
```

Steps:
1. **Prompts for Flow credentials** (or uses `FLOWBIO_USERNAME` / `FLOWBIO_PASSWORD` if already set)
2. Compiles annotation + scripts
3. Runs **prefetch** → polls every **4 minutes** until done
4. Runs **clean_fastq.sh** if needed → polls until done
5. Re-compiles with real FASTQs
6. Runs **upload_live.sh** → polls every 4 minutes
7. Verifies **analysis_params.confirmed.json** matches `pipeline_params.json`
8. Runs **run_analysis.sh** → polls every 4 minutes

Logs per step: `OUTPUT/logs/prefetch.log`, `clean.log`, `upload.log`, `analysis.log`

## Visible terminal (recommended)

Long steps run in the background; status prints every 4 minutes. For a **live scrolling log**, open a second terminal:

```bash
tail -f /tmp/gse105082-prefetch/logs/workflow.log   # if using run_workflow.sh
tail -f /tmp/gse105082-prefetch/logs/upload.log       # during upload
```

Or run the generated all-in-one script in its own terminal (uses `tee`):

```bash
bash /tmp/gse105082-prefetch/run_workflow.sh
# WSL/Linux pop-out:
# gnome-terminal -- bash -lc 'tail -f /tmp/gse105082-prefetch/logs/workflow.log'
```

A dedicated terminal tab is useful so agent-driven steps stay visible while you work elsewhere in the IDE. Cursor does not auto-pop a terminal today — `tail -f` on `logs/*.log` is the practical equivalent.

## Output artifacts

| File | Stage |
|------|-------|
| `.flow_credentials.env` | Credential prompt (mode 600, never commit) |
| `run_workflow.sh` | All-in-one script with `tee` for visible logs |
| `CONFIRM_BARCODES.md` | Barcode hook (sources + evidence) |
| `barcode_proposals.json` | Barcode proposals (set `status: confirmed`) |
| `annotation.csv` | Upload sheet (preferred; avoids XLSX font issues) |
| `annotation.xlsx` | Optional XLSX export |
| `pipeline_params.json` | Derived analysis params |
| `CONFIRM_ANALYSIS_PARAMS.md` | Analysis params hook |
| `analysis_params.confirmed.json` | Confirmed analysis params (required by `run_analysis.sh`) |
| `prefetch.sh` / `clean_fastq.sh` / `upload_live.sh` / `run_analysis.sh` | Stage scripts |
| `logs/*.log` | Per-step logs for `tail -f` |
