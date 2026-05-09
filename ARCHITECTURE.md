# Architecture

## Problem statement

A research team produces studies with a fixed structure: dataset → analysis → charts → narrative → deliverable. Each study takes ~1 week of manual work, mostly because:

1. **Data validation is error-prone and manual** — analyst eyeballs columns, often misses dtype issues / mislabeled categories until after publication.
2. **Chart formatting is tedious** — every study reformats the same chart-types to brand spec.
3. **Writing the narrative requires reading the data** — analyst alternates between spreadsheet and document.
4. **Assembly is fragile** — copy-paste chart images into Word, manually format references.

If this loop runs N times a quarter, time per study compounds and team velocity caps at headcount.

## Goal

Push as much of the loop into a **deterministic + LLM-augmented pipeline** so the analyst writes only the **study spec** (the question, the dataset, the desired chart-types) and gets back a draft deliverable in minutes.

Target metrics:
- **Latency:** ~10 min/study (down from ~1 week)
- **Cost:** ~$0.80/study (LLM call cost dominates; chart + docx are free)
- **Throughput:** N parallel studies at same headcount

## Design

### 1. Orchestration: n8n

[n8n](https://n8n.io) chosen over alternatives (Airflow, Prefect, custom queue) because:

- **Native LLM + HTTP nodes** — no glue code to call OpenAI / runner API.
- **Visual debug** — analyst-friendly, anyone on team can trace why a run failed.
- **Persisted runs** — built-in run history, retry logic, scheduled triggers.
- **Self-hostable** — no per-execution pricing.

The workflow is a DAG of nodes: load spec → call runner `/dataset-preview` → call OpenAI with preview as context → call runner `/render-chart` (in parallel for each chart spec) → call runner `/assemble-docx` → emit deliverable to storage.

### 2. Sandboxed Python runner

Generic Flask service ([`src/runner.py`](src/runner.py)). Endpoints:

| endpoint | purpose |
|---|---|
| `/health` | Liveness check + version. |
| `/dataset-preview` | Reads a dataset (`.parquet`, `.xlsx`, `.csv`), profiles columns (null %, cardinality, dtype inference, value-range), emits validation warnings. |
| `/run` | Executes an arbitrary script in the runner's sandbox with a timeout, captures stdout/stderr/exit-code as JSON. |

Sandboxing:
- Runs as **non-root user** inside container.
- **Read-only mounts** for dataset volumes; only `/output` writeable.
- **CPU + memory limits** via Docker.
- **Network egress allowlist** (LLM API only, not arbitrary outbound).

### 3. LLM-driven narrative

The `dataset-preview` output is the primary context for the LLM. The prompt has three sections:

1. **System** — role-prime ("you are a research analyst"), output schema (Pydantic-style JSON), style guidance.
2. **Data context** — dataset preview + study spec + any prior-study summaries.
3. **Task** — answer the study question.

Output is **JSON-mode** with explicit fields: `headline`, `key_findings` (list), `narrative` (markdown), `chart_specs` (list of `{type, x, y, series, title}`), `caveats` (list).

This reduces hallucination because:
- Model never invents column names — it sees them in preview.
- Validation warnings (e.g. "column 'state' contains country names like 'France'") propagate to the model's caveats.
- Structured output → schema-validated → fail loudly if model deviates.

### 4. Chart utility

[`src/chart_utility.py`](src/chart_utility.py) — `matplotlib`-based publication-quality charts.

Each chart spec from the LLM gets rendered by a typed function:

- `chart_type=horizontal_bar` → `_render_hbar(spec, df)`
- `chart_type=line_multi` → `_render_line(spec, df)`
- ...

Smart defaults handle:
- Label collision avoidance (hide labels for thin bars/small slices)
- Adaptive font sizes based on data density
- Brand-color rotation
- Footer with study UUID + timestamp for traceability

### 5. DOCX assembly

[`src/post_to_docx.py`](src/post_to_docx.py) — generic `python-docx` builder. Takes the LLM's narrative + rendered chart paths + metadata; emits a single `.docx` with title, body, embedded charts, footer.

## Trade-offs

**Why not a single Python script?** n8n adds visual debuggability + retry logic + orchestration UX for non-engineers on the team. The cost is one extra service to host.

**Why not a vector DB / RAG?** Studies are stateless — each run reads a fresh dataset. RAG would add complexity without benefit.

**Why JSON-mode over function-calling?** Cheaper, simpler, schema-validated. Function-calling adds round-trips for marginal benefit at this latency budget.

**Why matplotlib over Plotly / Vega?** Static charts, tight font/spacing control needed for print-quality output. Plotly was tried but hard to brand consistently.

## Caveats

- This template is **infrastructure**, not data. Bring your own dataset + study spec format.
- LLM cost scales with prompt size — keep `dataset-preview` summaries terse (sample rows, not full dump).
- Sandbox isolation is **defense in depth**, not a security panacea — never run untrusted analyst scripts; only your own code.

---

This is an opinionated reference, not a framework. Adapt aggressively to your team's needs.
