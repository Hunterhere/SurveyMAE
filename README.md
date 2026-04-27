# SurveyMAE

**SurveyMAE** is a LangGraph-based multi-agent evaluation framework for assessing the quality of LLM-generated academic surveys.

## Highlights

- Multi-dimensional review across factuality, expertise, readability, correction, and final reporting agents.
- Evidence-grounded scoring with citation validation, citation graph analysis, temporal coverage, structure analysis, and literature search signals.
- Multi-model correction for high hallucination-risk dimensions, including variance records for disagreement.
- Config-driven runtime through YAML files and environment variables.
- Extensible registries for metrics, evidence routing, tools, and agent dimensions.

## Quick Start

### Requirements

- Python 3.12+
- uv
- Optional: Docker, when using GROBID as a PDF reference parsing backend

### Install

```bash
uv sync
cp .env.example .env
```

Fill in your own API keys in the local `.env` file.

### Run an Evaluation

```bash
uv run python -m src.main path/to/survey.pdf
uv run python -m src.main path/to/survey.pdf -o ./output
uv run python -m src.main path/to/survey.pdf -c config/main.yaml -v
```

### Start the Local Web UI

Start the frontend-backed FastAPI server on Windows PowerShell:

```powershell
.\scripts\start_server.ps1
.\scripts\start_server.ps1 -Port 8080
```

Start it on Linux/macOS:

```bash
scripts/start_server.sh
scripts/start_server.sh --port 8080
```

The server defaults to `http://localhost:8000` with auto-reload enabled. Press `Ctrl+C` in the terminal to stop it.

## Environment

Use `.env.example` as the template for local configuration:

```bash
OPENAI_API_KEY=
ANTHROPIC_API_KEY=
DASHSCOPE_API_KEY=
DEEPSEEK_API_KEY=
SEMANTIC_SCHOLAR_API_KEY=
OPENALEX_EMAIL=
DATALAB_API_KEY=
GROBID_URL=
```

The template contains the full field list. Fill only the providers and tools you plan to use.

## Optional GROBID Backend

SurveyMAE can use GROBID to improve PDF reference parsing. The examples below follow the official GROBID Docker documentation: <https://grobid.readthedocs.io/en/latest/Grobid-docker/>.

Pull the CRF-only image:

```bash
docker pull grobid/grobid:0.9.0-crf
```

Start, inspect, and stop GROBID on Windows PowerShell:

```powershell
.\scripts\grobid.ps1 -Action start
.\scripts\grobid.ps1 -Action status
.\scripts\grobid.ps1 -Action stop
```

Start, inspect, and stop GROBID on Linux/macOS:

```bash
scripts/grobid.sh start
scripts/grobid.sh status
scripts/grobid.sh stop
```

Both scripts default to `grobid/grobid:0.9.0-crf`, container name `grobid`, host port `8070`, and an 8 GB memory limit. Set `GROBID_URL=http://localhost:8070` in `.env` if you need an explicit backend URL.

## Project Layout

```text
SurveyMAE/
├── config/                  # LLM, search, agent, and prompt configuration
├── docs/                    # Developer guide, design notes, and Chinese README
├── scripts/                 # Utility scripts, including web server and GROBID helpers
├── src/
│   ├── agents/              # Agent implementations
│   ├── core/                # State, config, logging, and MCP client code
│   ├── graph/               # LangGraph nodes, edges, and workflow builder
│   └── tools/               # PDF parsing, citation, search, and graph tools
└── tests/                   # Unit and integration tests
```

## Secondary Development

SurveyMAE is designed to be configurable and extensible. See [docs/DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) for customization details, including:

- Tool customization: [Customize the PDF parsing backend](docs/DEVELOPER_GUIDE.md#95-customize-the-pdf-parsing-backend)
- Metric customization: [Add a new tool metric](docs/DEVELOPER_GUIDE.md#91-add-a-new-tool-metric)
- Agent and sub-dimension extension: [Add or modify an agent sub-dimension](docs/DEVELOPER_GUIDE.md#92-add-or-modify-an-agent-sub-dimension)
- Evidence-to-dimension routing: [Metrics and agent mapping](docs/DEVELOPER_GUIDE.md#6-metrics-and-agent-mapping)
- Testing and code checks: [Testing and quality checks](docs/DEVELOPER_GUIDE.md#10-testing-and-quality-checks)

Chinese documentation is available at [docs/README.zh-CN.md](docs/README.zh-CN.md), and the Chinese developer guide is available at [docs/DEVELOPER_GUIDE.zh-CN.md](docs/DEVELOPER_GUIDE.zh-CN.md).

## Testing

Unit tests cover deterministic logic and should not require external services or real API keys:

```bash
uv run pytest tests/unit
uv run pytest tests/unit/test_evidence_dispatch.py
uv run pytest tests/unit/test_aggregator.py tests/unit/test_state.py
```

Integration tests exercise real pipeline boundaries such as PDF parsing, GROBID, external search providers, and citation graph generation. They may require Docker services, API keys, or sample PDFs:

```bash
uv run pytest tests/integration
uv run pytest tests/integration/test_citation_graph_pipeline.py
uv run pytest tests/integration/test_citation_grobid.py
```

Code quality checks:

```bash
uv run ruff format .
uv run ruff check .
uv run mypy src/
```

## Acknowledgements

SurveyMAE reuses literature-search components from [BibGuard](https://github.com/HaucaVN/BibGuard) under `src/tools/fetchers/`, supports [GROBID](https://github.com/grobidOrg/grobid) as an optional PDF reference parsing backend, and can use [Marker](https://github.com/datalab-to/marker) for high-quality PDF-to-Markdown parsing.

## License

MIT License
