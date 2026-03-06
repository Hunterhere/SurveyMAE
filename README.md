# SurveyMAE

**SurveyMAE**（Survey Multi-Agent Evaluation）是一个基于 LangGraph 的多智能体动态评测框架，用于评估 LLM 生成的学术综述（Survey）质量。

**核心特性**
- 多维度评估：五个专业智能体从不同角度评估综述质量
- 辩论机制：支持多轮辩论达成共识
- MCP 协议：工具可通过 MCP 协议暴露和调用
- 可扩展架构：易于添加新的评估维度和智能体
- 配置驱动：所有配置外部化，支持 YAML 管理

**评估维度**
| 智能体 | 维度 | 描述 |
|--------|------|------|
| VerifierAgent | 事实性 | 幻觉检测、引用验证 |
| ExpertAgent | 深度 | 技术准确性、逻辑连贯性 |
| ReaderAgent | 可读性 | 覆盖范围、清晰度 |
| CorrectorAgent | 平衡性 | 偏见检测、观点平衡 |
| ReportAgent | 报告生成 | 聚合评测结果、生成最终报告 |

**快速开始**
前置要求
- Python 3.12+
- uv 包管理器

安装与运行
```bash
# 安装依赖
uv sync

# 配置环境变量
# 项目根目录已有 .env 文件，可直接编辑
# OPENAI_API_KEY=your-key-here

# 运行评测（输入 PDF）
uv run python -m src.main path/to/survey.pdf

# 指定输出文件
uv run python -m src.main path/to/survey.pdf -o report.md

# 使用自定义配置
uv run python -m src.main path/to/survey.pdf -c config/main.yaml

# 启用详细日志
uv run python -m src.main path/to/survey.pdf -v
```

**项目结构**
```
SurveyMAE/
├── config/                  # 配置文件目录
│   ├── main.yaml           # 主配置（LLM、Agent、MCP 服务器等）
│   └── prompts/            # Agent System Prompt 模板
├── src/
│   ├── main.py             # CLI 入口
│   ├── core/               # 核心框架层
│   ├── agents/             # 智能体实现
│   ├── graph/              # LangGraph 编排层
│   └── tools/              # 工具实现（PDF/引用等）
└── tests/                  # 测试
```

**配置说明**
主配置文件 `config/main.yaml` 覆盖 LLM、Agent、辩论策略、MCP 服务、引用抽取等配置。

`.env` 示例：
```bash
OPENAI_API_KEY=sk-your-key-here
# 可选
ANTHROPIC_API_KEY=sk-ant-your-key-here
OPENAI_BASE_URL=https://api.openai.com/v1
```

**工具与 MCP**
- PDF 解析工具：`src/tools/pdf_parser.py`（基于 `pymupdf4llm`）
- 引用检查工具：`src/tools/citation_checker.py`
- MCP Server：`src/tools/*_server.py`

可选后端 GROBID：
```bash
docker compose -f docker-compose.grobid.yaml up -d
```

**开发与测试**
```bash
# 运行测试
uv run pytest

# 代码格式化
uv run ruff format .

# 静态分析
uv run ruff check .

# 类型检查
uv run mypy src/
```

**贡献指南**
1. Fork 项目
2. 创建功能分支：`git checkout -b feature/my-feature`
3. 提交更改：`git commit -am 'Add new feature'`
4. 推送分支：`git push origin feature/my-feature`
5. 创建 Pull Request

**致谢**
本项目复用 BibGuard 的文献检索组件，代码位于 `src/tools/fetchers/`。

**许可证**
MIT License
