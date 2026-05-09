"""Generic sandboxed Python runner for research-automation pipelines.

Endpoints:
- GET  /health             — liveness + version
- POST /run                — execute a script in /app with timeout, capture stdout/stderr/exit
- POST /dataset-preview    — load a tabular dataset, profile + validate, return JSON

Configuration via environment variables (see docker/Dockerfile):
- DATASETS_DIR   — read-only mount path for input datasets
- OUTPUT_DIR     — writeable mount path for run artifacts
- RUN_TIMEOUT_S  — default per-run timeout (sec)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import traceback
import uuid
from pathlib import Path

from flask import Flask, jsonify, request

app = Flask(__name__)

DATASETS_DIR = Path(os.environ.get("DATASETS_DIR", "/app/datasets"))
OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "/app/output"))
RUN_TIMEOUT_S = int(os.environ.get("RUN_TIMEOUT_S", "300"))

VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    return jsonify({
        "status": "ok",
        "version": VERSION,
        "python": sys.version.split()[0],
        "datasets_dir": str(DATASETS_DIR),
        "output_dir": str(OUTPUT_DIR),
    })


# ---------------------------------------------------------------------------
# /run
# ---------------------------------------------------------------------------
@app.post("/run")
def run_script():
    """Execute an arbitrary script under sandbox. Returns JSON of stdout/stderr/exit."""
    payload = request.get_json(force=True, silent=True) or {}
    script_path = payload.get("script_path", "")
    args = payload.get("args", [])
    timeout = int(payload.get("timeout", RUN_TIMEOUT_S))
    cwd = payload.get("cwd", "/app")

    if not script_path:
        return jsonify({"success": False, "error": "script_path required"}), 400
    if not Path(script_path).is_file():
        return jsonify({"success": False, "error": f"script not found: {script_path}"}), 404

    run_id = uuid.uuid4().hex[:12]
    try:
        proc = subprocess.run(
            ["python", script_path, *map(str, args)],
            cwd=cwd,
            timeout=timeout,
            capture_output=True,
            text=True,
        )
        return jsonify({
            "success": proc.returncode == 0,
            "run_id": run_id,
            "exit_code": proc.returncode,
            "stdout": proc.stdout[-50_000:],   # cap to avoid huge response
            "stderr": proc.stderr[-50_000:],
        })
    except subprocess.TimeoutExpired:
        return jsonify({
            "success": False,
            "run_id": run_id,
            "error": f"timeout after {timeout}s",
        }), 408
    except Exception as e:
        return jsonify({
            "success": False,
            "run_id": run_id,
            "error": str(e),
            "traceback": traceback.format_exc()[-10_000:],
        }), 500


# ---------------------------------------------------------------------------
# /dataset-preview
# ---------------------------------------------------------------------------
@app.post("/dataset-preview")
def dataset_preview():
    """Profile + validate a tabular dataset. Returns JSON suitable as LLM context."""
    import pandas as pd  # local import to keep cold-start fast

    payload = request.get_json(force=True, silent=True) or {}
    rel_path = payload.get("path")
    sample_rows = int(payload.get("sample_rows", 5))

    if not rel_path:
        return jsonify({"error": "path required"}), 400

    full_path = DATASETS_DIR / rel_path
    if not full_path.exists():
        return jsonify({"error": f"dataset not found: {rel_path}"}), 404

    suffix = full_path.suffix.lower()
    try:
        if suffix == ".csv":
            df = pd.read_csv(full_path)
        elif suffix == ".parquet":
            df = pd.read_parquet(full_path)
        elif suffix in (".xlsx", ".xls"):
            df = pd.read_excel(full_path)
        else:
            return jsonify({"error": f"unsupported extension: {suffix}"}), 400
    except Exception as e:
        return jsonify({"error": f"could not load: {e}"}), 500

    profile = []
    warnings = []

    for col in df.columns:
        s = df[col]
        col_info = {
            "name": col,
            "dtype": str(s.dtype),
            "n_total": int(len(s)),
            "n_null": int(s.isna().sum()),
            "null_pct": round(float(s.isna().mean() * 100), 2),
            "n_unique": int(s.nunique(dropna=True)),
        }

        # Numeric column → range stats
        if pd.api.types.is_numeric_dtype(s):
            col_info.update({
                "min": _to_jsonable(s.min()),
                "max": _to_jsonable(s.max()),
                "median": _to_jsonable(s.median()),
            })

        # Object/string column → small-cardinality value list
        elif s.dtype == object and s.nunique(dropna=True) <= 25:
            col_info["values"] = [_to_jsonable(v) for v in s.dropna().unique().tolist()]

        # Validation warnings: country names in state-like columns
        if "state" in col.lower() and s.dtype == object:
            sample_vals = set(s.dropna().astype(str).head(200).tolist())
            country_hits = {"United States", "USA", "France", "Germany", "Russia"} & sample_vals
            if country_hits:
                warnings.append({
                    "column": col,
                    "type": "category-leak",
                    "detail": f"country names found in state-like column: {sorted(country_hits)}",
                })

        profile.append(col_info)

    return jsonify({
        "path": rel_path,
        "n_rows": int(len(df)),
        "n_columns": int(len(df.columns)),
        "columns": profile,
        "sample": [
            {col: _to_jsonable(row[col]) for col in df.columns}
            for _, row in df.head(sample_rows).iterrows()
        ],
        "validation_warnings": warnings,
    })


def _to_jsonable(o):
    """Best-effort conversion to JSON-serializable scalar."""
    import math

    import numpy as np
    import pandas as pd
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        f = float(o)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return None if pd.isna(o) else o.isoformat()
    if isinstance(o, pd.Timedelta):
        return o.total_seconds()
    return o if (o is None or isinstance(o, (str, int, float, bool))) else str(o)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))
