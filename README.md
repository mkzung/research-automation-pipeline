# Research-Automation Pipeline · Reference Architecture

> 📝 **About this repo.** This is a **generic derivative template** distilled from a production pipeline I architected at **Stanford GSB Venture Capital Initiative** (under Prof. Ilya Strebulaev, Faculty Director, VCI). The template is published with advisor permission as a methodology reference — the original Stanford codebase, datasets (PitchBook + internal), business logic, and infrastructure configs are **not** included. Everything here is generic, reusable, and self-contained.

The original pipeline compressed per-study research processing from **~1 week of manual work to ~10 minutes at ~$0.80 / study**, freeing the team to run more parallel studies at the same headcount.

---

## What this template demonstrates

A **four-stage research-automation pattern** for any team that needs to repeatedly transform structured data + qualitative judgement into publishable artifacts (charts, narratives, reports):

1. **Trigger / orchestration** — `n8n` workflow takes a study spec, schedules execution, retries on failure, persists run metadata.
2. **Data preview + validation** — sandboxed Python container reads dataset(s), profiles columns (null %, cardinality, dtypes, value ranges), and emits validation warnings before the LLM ever sees the data.
3. **LLM-driven narrative** — structured prompt to OpenAI (or any chat-completion API) over the previewed data; output schema enforced via JSON-mode + Pydantic-style validation.
4. **Artifact assembly** — Python utilities render publication-quality charts (`matplotlib`) and assemble a deliverable document (`python-docx`).

The operator only writes the **study spec** (a YAML/JSON describing the question, dataset, and output style); the pipeline produces the artifact.

---

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for the full diagram and design rationale.

```
┌──────────────────┐
│  Study spec      │  ← author writes this
│  (YAML / JSON)   │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐    ┌─────────────────────┐
│  n8n orchestrator│───▶│  Python runner API  │
│  (workflow logic)│◀───│  (sandboxed Flask)  │
└──────────────────┘    └─────────┬───────────┘
                                  │
            ┌─────────────────────┼──────────────────────┐
            ▼                     ▼                      ▼
   ┌────────────────┐   ┌──────────────────┐   ┌──────────────────┐
   │ data preview + │   │ LLM narrative     │   │ chart utility    │
   │ validation     │   │ (OpenAI JSON mode)│   │ (matplotlib)     │
   └────────────────┘   └──────────────────┘   └──────────────────┘
                                  │
                                  ▼
                       ┌──────────────────┐
                       │  docx assembly   │  ──▶ deliverable
                       └──────────────────┘
```

---

## What's in this repo

| path | purpose |
|---|---|
| [`src/runner.py`](src/runner.py) | Generic Flask runner — `/run`, `/health`, `/dataset-preview` endpoints. Sandbox script execution + structured JSON responses. |
| [`src/chart_utility.py`](src/chart_utility.py) | `matplotlib`-based publication-quality chart generator. Adaptive label hiding, smart axis sizing, dark-mode-friendly palettes. |
| [`src/post_to_docx.py`](src/post_to_docx.py) | Generic `python-docx` post → DOCX converter with title, body, footer, optional metadata. |
| [`workflows/sample_pipeline.json`](workflows/sample_pipeline.json) | Generic n8n workflow demonstrating the orchestration pattern (load spec → preview → LLM → render → docx). |
| [`docker/Dockerfile`](docker/Dockerfile) + [`docker-compose.yml`](docker/docker-compose.yml) | Containerized runtime. |
| [`requirements.txt`](requirements.txt) | Pinned Python deps. |

---

## Try it

```bash
# 1. Build + run the sandboxed runner
cd docker && docker compose up -d
# 2. Health check
curl http://localhost:5000/health
# 3. Send a sample run request
curl -X POST http://localhost:5000/run \
     -H "Content-Type: application/json" \
     -d '{"script_path": "/app/scripts/example.py", "args": []}'
```

For the full automation chain, import [`workflows/sample_pipeline.json`](workflows/sample_pipeline.json) into a self-hosted [n8n](https://n8n.io/) instance and configure the OpenAI credential.

---

## Design decisions worth borrowing

- **Sandbox the Python runner.** Running arbitrary scripts is dangerous; isolate via Docker network + non-root user + read-only mounts where possible.
- **Always preview before LLM-ing.** Showing the LLM column profile + sample rows + warnings (e.g. "country names found in state column") cuts hallucination dramatically and surfaces dataset issues early.
- **Force JSON-mode with a schema.** Free-form LLM output is unparseable; structured-output via JSON-mode + a Pydantic schema makes pipeline reliable.
- **Keep narrative + chart generation separate.** Easier to swap models, change brand styling, regenerate one without re-running the LLM.
- **Persist run metadata.** Every run gets a UUID, timestamps, model + prompt versions, validation warnings, output paths. Reproducibility + debugging.

---

## License

MIT — see [LICENSE](LICENSE). Original Stanford VCI codebase, datasets, configs, and Stanford-internal business logic are **not** part of this repository.

---

## About

**Max Gorbuk** · [github.com/mkzung](https://github.com/mkzung) · [linkedin.com/in/gorbuk](https://linkedin.com/in/gorbuk) · gorbuk@stanford.edu

Researcher, Stanford GSB Venture Capital Initiative (Jul 2025 – present).
