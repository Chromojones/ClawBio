"""Full automated workflow: credentials → download → clean → upload → analysis."""

from __future__ import annotations

import os
import shlex
import stat
import subprocess
import sys
from pathlib import Path

from lib.credentials import ensure_flow_credentials, env_file_source_line
from lib.process_runner import DEFAULT_POLL_INTERVAL_SEC, run_shell_step


def write_run_workflow_script(
    output_dir: Path,
    *,
    env_path: Path,
    fastq_dir: Path,
    poll_interval: int,
    compile_argv: list[str],
) -> Path:
    """
    Generate run_workflow.sh for a visible terminal session (tee to logs/workflow.log).

    Open live output in another terminal:
      tail -f OUTPUT/logs/workflow.log
    Or pop a terminal (Linux):
      xterm -e 'tail -f OUTPUT/logs/workflow.log'
      gnome-terminal -- bash -lc 'tail -f OUTPUT/logs/workflow.log'
    """
    logs = output_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    script = output_dir / "run_workflow.sh"

    compile_cmd = " ".join(shlex.quote(a) for a in compile_argv)
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "# flow-compile automated workflow — run in a terminal for live output",
        f"OUTPUT={shlex.quote(str(output_dir.resolve()))}",
        f"FASTQ_DIR={shlex.quote(str(fastq_dir.resolve()))}",
        f"POLL={poll_interval}",
        f"ENV_FILE={shlex.quote(str(env_path.resolve()))}",
        f"COMPILE_CMD={shlex.quote(compile_cmd)}",
        "",
        "mkdir -p \"$OUTPUT/logs\"",
        "exec > >(tee -a \"$OUTPUT/logs/workflow.log\") 2>&1",
        "",
        "echo \"=== flow-compile automated workflow $(date -Is) ===\"",
        "source \"$ENV_FILE\"",
        "",
        "run_step() {",
        "  local name=\"$1\" script=\"$2\" log=\"$3\"",
        "  echo \"→ $name\"",
        "  bash \"$script\" > \"$log\" 2>&1 &",
        "  local pid=$!",
        "  while kill -0 \"$pid\" 2>/dev/null; do",
        "    echo \"… $name still running ($(date +%H:%M:%S)); log: $log\"",
        "    tail -n 1 \"$log\" 2>/dev/null || true",
        "    sleep \"$POLL\"",
        "  done",
        "  wait \"$pid\"",
        "  echo \"✓ $name done\"",
        "}",
        "",
        "eval \"$COMPILE_CMD\"",
        "",
        "if [[ -f \"$OUTPUT/prefetch.sh\" ]]; then",
        "  FASTQ_DIR=\"$FASTQ_DIR\" run_step prefetch \"$OUTPUT/prefetch.sh\" \"$OUTPUT/logs/prefetch.log\"",
        "fi",
        "",
        "eval \"$COMPILE_CMD --fastq-dir $FASTQ_DIR\"",
        "",
        "if [[ -f \"$OUTPUT/umi_extract.sh\" ]]; then",
        "  run_step umi_extract \"$OUTPUT/umi_extract.sh\" \"$OUTPUT/logs/umi_extract.log\"",
        "fi",
        "",
        "eval \"$COMPILE_CMD --fastq-dir $FASTQ_DIR\"",
        "",
        "if [[ -f \"$OUTPUT/clean_fastq.sh\" ]]; then",
        "  run_step clean \"$OUTPUT/clean_fastq.sh\" \"$OUTPUT/logs/clean.log\"",
        "fi",
        "",
        "eval \"$COMPILE_CMD --fastq-dir $FASTQ_DIR\"",
        "",
        "if [[ -f \"$OUTPUT/upload_live.sh\" ]]; then",
        "  run_step upload \"$OUTPUT/upload_live.sh\" \"$OUTPUT/logs/upload.log\"",
        "fi",
        "",
        "if [[ -f \"$OUTPUT/run_analysis.sh\" ]]; then",
        "  run_step analysis \"$OUTPUT/run_analysis.sh\" \"$OUTPUT/logs/analysis.log\"",
        "fi",
        "",
        "echo \"=== workflow complete $(date -Is) ===\"",
    ]
    script.write_text("\n".join(lines) + "\n")
    script.chmod(stat.S_IRWXU | stat.S_IRGRP | stat.S_IROTH)
    return script


def run_automated_workflow(
    output_dir: Path,
    fastq_dir: Path,
    *,
    compile_fn,
    compile_kwargs: dict,
    poll_interval: int = DEFAULT_POLL_INTERVAL_SEC,
    prompt_credentials: bool = True,
    skip_download: bool = False,
    skip_upload: bool = False,
    skip_analysis: bool = False,
) -> int:
    """
    Python-driven automation with 4-minute polling between long steps.
    compile_fn: callable returning same as flow_compile.run_pipeline path via re-invocation.
    """
    env_path = ensure_flow_credentials(output_dir, prompt=prompt_credentials)
    logs = output_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)

    # Initial compile (may pause for barcodes — caller should handle)
    result, paused = compile_fn(**compile_kwargs)
    if paused or result is None:
        return 3

    fastq_dir.mkdir(parents=True, exist_ok=True)
    os.environ["FASTQ_DIR"] = str(fastq_dir)

    if not skip_download and (output_dir / "prefetch.sh").exists():
        rc = run_shell_step(
            "prefetch (SRA download)",
            output_dir / "prefetch.sh",
            logs / "prefetch.log",
            poll_interval=poll_interval,
            extra_env={"FASTQ_DIR": str(fastq_dir)},
        )
        if rc != 0:
            return rc

    # Refresh annotation / scripts with real FASTQs (writes clean_fastq.sh when needed)
    compile_kwargs = {**compile_kwargs, "fastq_dir": fastq_dir}
    result, paused = compile_fn(**compile_kwargs)
    if paused or result is None:
        return 3

    if (output_dir / "umi_extract.sh").exists():
        rc = run_shell_step(
            "FLASH UMI extract (umi_tools)",
            output_dir / "umi_extract.sh",
            logs / "umi_extract.log",
            poll_interval=poll_interval,
        )
        if rc != 0:
            return rc
        result, paused = compile_fn(**compile_kwargs)
        if paused or result is None:
            return 3

    if (output_dir / "clean_fastq.sh").exists():
        rc = run_shell_step(
            "header clean (removespace)",
            output_dir / "clean_fastq.sh",
            logs / "clean.log",
            poll_interval=poll_interval,
        )
        if rc != 0:
            return rc
        result, paused = compile_fn(**compile_kwargs)
        if paused or result is None:
            return 3

    if not skip_upload and (output_dir / "upload_live.sh").exists():
        rc = run_shell_step(
            "Flow upload",
            output_dir / "upload_live.sh",
            logs / "upload.log",
            poll_interval=poll_interval,
            extra_env={
                "FLOWBIO_USERNAME": os.environ["FLOWBIO_USERNAME"],
                "FLOWBIO_PASSWORD": os.environ["FLOWBIO_PASSWORD"],
            },
        )
        if rc != 0:
            return rc
        upload_log = (logs / "upload.log").read_text(errors="replace")
        if "successful=0" in upload_log:
            print("Upload failed — check logs/upload.log", file=sys.stderr)
            return 1
        if "failed=" in upload_log and "failed=0" not in upload_log:
            print("Upload had failures — check logs/upload.log", file=sys.stderr)
            return 1

    if not skip_analysis and (output_dir / "run_analysis.sh").exists():
        rc = run_shell_step(
            "Flow CLIP analysis",
            output_dir / "run_analysis.sh",
            logs / "analysis.log",
            poll_interval=poll_interval,
            extra_env={
                "FLOWBIO_USERNAME": os.environ["FLOWBIO_USERNAME"],
                "FLOWBIO_PASSWORD": os.environ["FLOWBIO_PASSWORD"],
            },
        )
        if rc != 0:
            return rc

    print(f"✓ Automated workflow complete. Master log: {logs / 'workflow.log'}")
    return 0
