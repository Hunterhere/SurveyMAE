"""SurveyMAE Main Entry Point.

CLI interface for running the multi-agent survey evaluation framework.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Load environment variables from .env file
from dotenv import load_dotenv

_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / ".env")

from src.core.config import load_config, SurveyMAEConfig
from src.core.log import (
    get_console,
    get_run_stats,
    log_pipeline_step,
    log_run_summary,
    setup_logging,
)
from src.core.state import SurveyState
from src.graph.builder import compile_workflow, create_workflow
from src.tools.pdf_parser import PDFParser


def _generate_run_id(pdf_path: str) -> str:
    """Generate run_id from PDF path and current time."""
    pdf_hash = hashlib.md5(pdf_path.encode()).hexdigest()[:8]
    return f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{pdf_hash}"


async def run_evaluation(
    pdf_path: str,
    config: Optional[SurveyMAEConfig] = None,
    output_dir: Optional[str] = None,
) -> tuple[str, str]:
    """Run the survey evaluation workflow.

    Args:
        pdf_path:   Path to the survey PDF to evaluate.
        config:     Optional configuration.
        output_dir: Output directory for reports. Defaults to output/reports.

    Returns:
        Tuple of (evaluation_report, run_dir).
    """
    run_id = _generate_run_id(pdf_path)
    if output_dir is None:
        output_dir = "./output"
    run_dir = Path(output_dir) / "runs" / run_id

    # Initialize logging (creates run_dir/logs/run.log)
    logger = setup_logging(run_dir=run_dir, pdf_path=pdf_path)

    logger.info("SurveyMAE 评测启动 | PDF: %s", pdf_path)

    # Parse the PDF
    parser = PDFParser()
    parsed_content = parser.parse(pdf_path)

    # Initialize state with all required fields
    initial_state: SurveyState = {
        "source_pdf_path": pdf_path,
        "parsed_content": parsed_content,
        "section_headings": [],
        "tool_evidence": {},
        "ref_metadata_cache": {},
        "topic_keywords": [],
        "field_trend_baseline": {},
        "candidate_key_papers": [],
        "evaluations": [],
        "debate_history": [],
        "sections": {},
        "agent_outputs": {},
        "aggregated_scores": {},
        "current_round": 0,
        "consensus_reached": False,
        "final_report_md": "",
        "metadata": {
            "source": pdf_path,
            "domain": "general",
        },
        "dispatch_specs": {},
        "metrics_index": {},
    }

    # Create and compile the workflow (pass run_dir so ResultStore uses the same)
    workflow = create_workflow(config, run_dir=str(run_dir))
    app = compile_workflow(workflow, config)

    # Run the workflow
    config_id = {"configurable": {"thread_id": f"eval_{Path(pdf_path).stem}"}}

    logger.info("Running evaluation workflow...")
    final_state = await app.ainvoke(initial_state, config=config_id)

    report = final_state.get("final_report_md", "")

    # Save report to run_dir/reports/
    report_dir = run_dir / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    pdf_name = Path(pdf_path).stem
    report_path = report_dir / f"{pdf_name}_{timestamp}.md"
    report_path.write_text(report, encoding="utf-8")
    logger.info("报告已保存: %s", report_path)

    return report, str(run_dir)


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="SurveyMAE: Multi-Agent Dynamic Evaluation Framework for LLM-Generated Surveys",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "pdf_path",
        help="Path to the survey PDF file to evaluate",
    )

    parser.add_argument(
        "-c",
        "--config",
        help="Path to configuration file",
        default=None,
    )

    parser.add_argument(
        "-o",
        "--output-dir",
        help="Output base directory (default: ./output)",
        default=None,
    )

    # Logging control (mutually exclusive group)
    log_group = parser.add_mutually_exclusive_group()
    log_group.add_argument(
        "-v",
        "--verbose",
        help="Enable verbose logging (show DEBUG on console)",
        action="store_true",
    )
    log_group.add_argument(
        "-q",
        "--quiet",
        help="Quiet mode: suppress progress bars, console shows WARNING+ only",
        action="store_true",
    )

    parser.add_argument(
        "--log-level",
        help="Explicit console log level (overrides -v and -q)",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=None,
    )

    args = parser.parse_args()

    # Check if PDF file exists (use a minimal logger for this early check)
    import logging
    early_logger = logging.getLogger("surveymae.main")
    early_logger.setLevel(logging.INFO)
    if not Path(args.pdf_path).exists():
        early_logger.error("PDF file not found: %s", args.pdf_path)
        sys.exit(1)

    # Load configuration
    config = None
    if args.config:
        config = load_config(args.config)
        early_logger.info("Loaded configuration from: %s", args.config)

    # Run evaluation
    console = get_console()
    try:
        start_time = time.monotonic()
        report, run_dir = asyncio.run(
            run_evaluation(
                pdf_path=args.pdf_path,
                config=config,
                output_dir=args.output_dir,
            )
        )
        total_elapsed = time.monotonic() - start_time

        # Final summary
        stats = get_run_stats()
        log_run_summary(stats, total_elapsed)

        console.print()
        console.print(f"[bold green]评测完成[/bold green] │ 报告: {run_dir}/reports/")

    except Exception as e:
        early_logger.error("Evaluation failed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
