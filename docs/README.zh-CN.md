# SurveyMAE

**SurveyMAE**（Survey Multi-Agent Evaluation）是一个基于 LangGraph 的多智能体动态评测框架，用于评估 LLM 生成的学术综述质量。

## 核心特性

- 多维度评估：Verifier、Expert、Reader、Corrector 和 Reporter 共同完成综述质量诊断。
- 证据化评测：引用验证、引用图、时序覆盖、结构分布等工具证据进入 Agent 评分上下文。
- 多模型校正：Corrector 对高幻觉风险维度执行多模型投票并记录方差。
- 可扩展架构：指标、证据映射、Agent 和工具均可通过现有注册表与配置扩展。
- 配置驱动：LLM、检索源、评测策略和输出行为通过 YAML 与环境变量管理。

## 快速开始

### 前置要求

- Python 3.12+
- uv
- 可选：Docker（用于 GROBID 参考文献解析后端）

### 安装

```bash
uv sync
cp .env.example .env
```

在本地 `.env` 文件中填写你自己的 API Key。

### 运行评测

```bash
uv run python -m src.main path/to/survey.pdf
uv run python -m src.main path/to/survey.pdf -o ./output
uv run python -m src.main path/to/survey.pdf -c config/main.yaml -v
```

## GROBID 可选后端

SurveyMAE 可使用 GROBID 增强 PDF 参考文献解析。官方 Docker 文档见 <https://grobid.readthedocs.io/en/latest/Grobid-docker/>。

```bash
docker pull grobid/grobid:0.9.0-crf
```

Windows PowerShell：

```powershell
.\scripts\grobid.ps1 -Action start
.\scripts\grobid.ps1 -Action status
.\scripts\grobid.ps1 -Action stop
```

Linux/macOS shell：

```bash
scripts/grobid.sh start
scripts/grobid.sh status
scripts/grobid.sh stop
```

默认服务地址为 `http://localhost:8070`。如需显式配置：

```bash
GROBID_URL=http://localhost:8070
```

## 项目结构

```text
SurveyMAE/
├── config/                  # LLM、检索源、Agent 和 prompt 配置
├── docs/                    # 开发手册和设计文档
├── scripts/                 # 辅助脚本，包括 GROBID 容器管理
├── src/
│   ├── agents/              # Agent 实现
│   ├── core/                # 配置、状态、日志、MCP 客户端
│   ├── graph/               # LangGraph 编排节点和边
│   └── tools/               # PDF、引用、检索、图分析等工具
└── tests/                   # 单元测试和集成测试
```

## 二次开发

SurveyMAE 设计上支持配置与二次扩展。自定义方法详见 [DEVELOPER_GUIDE.zh-CN.md](DEVELOPER_GUIDE.zh-CN.md)，其中包括：

- 工具自定义：[自定义 PDF 解析后端](DEVELOPER_GUIDE.zh-CN.md#95-自定义-pdf-解析后端)
- 指标自定义：[添加新工具指标](DEVELOPER_GUIDE.zh-CN.md#91-添加新工具指标)
- Agent 与子维度扩展：[添加或修改 Agent 子维度](DEVELOPER_GUIDE.zh-CN.md#92-添加或修改-agent-子维度)
- 证据到评分维度的映射关系：[评估指标与 Agent 映射](DEVELOPER_GUIDE.zh-CN.md#6-评估指标与-agent-映射)
- 测试与代码检查：[测试与质量检查](DEVELOPER_GUIDE.zh-CN.md#10-测试与质量检查)

## 测试

单元测试覆盖确定性逻辑，通常不依赖外部服务或真实 API Key：

```bash
uv run pytest tests/unit
uv run pytest tests/unit/test_evidence_dispatch.py
uv run pytest tests/unit/test_aggregator.py tests/unit/test_state.py
```

集成测试覆盖真实流水线边界，例如 PDF 解析、GROBID、外部检索源和引用图生成，可能需要 Docker 服务、API Key 或样例 PDF：

```bash
uv run pytest tests/integration
uv run pytest tests/integration/test_citation_graph_pipeline.py
uv run pytest tests/integration/test_citation_grobid.py
```

代码质量检查：

```bash
uv run ruff format .
uv run ruff check .
uv run mypy src/
```

## 致谢

本项目复用 [BibGuard](https://github.com/HaucaVN/BibGuard) 的文献检索组件（`src/tools/fetchers/`），支持使用 [GROBID](https://github.com/grobidOrg/grobid) 作为可选的 PDF 参考文献解析后端，并可使用 [Marker](https://github.com/datalab-to/marker) 进行高质量 PDF-to-Markdown 解析。

## 许可证

本项目采用 [MIT License](../LICENSE) 开源许可。
