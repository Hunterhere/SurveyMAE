"""SurveyMAE Main Entry Point.

CLI interface for running the multi-agent survey evaluation framework.
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Load environment variables from .env file
from dotenv import load_dotenv

# Try to load .env from project root
_project_root = Path(__file__).parent.parent
load_dotenv(_project_root / ".env")

from src.core.config import load_config, SurveyMAEConfig
from src.core.state import SurveyState
from src.graph.builder import create_workflow, compile_workflow
from src.tools.pdf_parser import PDFParser
from src.tools.citation_checker import CitationChecker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def run_evaluation(
    pdf_path: str,
    config: Optional[SurveyMAEConfig] = None,
    output_path: Optional[str] = None,
) -> str:
    """Run the survey evaluation workflow.

    Args:
        pdf_path: Path to the survey PDF to evaluate.
        config: Optional configuration.
        output_path: Optional path to save the report.

    Returns:
        The evaluation report as markdown.
    """
    logger.info(f"Starting evaluation of: {pdf_path}")

    # Parse the PDF
    parser = PDFParser()
    parsed_content = parser.parse(pdf_path)

    # Initialize state with all required fields for Phase 2 workflow
    initial_state: SurveyState = {
        "source_pdf_path": pdf_path,
        "parsed_content": parsed_content,
        "section_headings": [],  # Will be populated by PDF parser or later nodes
        "tool_evidence": {},  # Populated by evidence_collection node
        "ref_metadata_cache": {},  # Populated by evidence_collection node
        "topic_keywords": [],  # Populated by evidence_collection node
        "field_trend_baseline": {},  # Populated by evidence_collection node
        "candidate_key_papers": [],  # Populated by evidence_collection node
        "evaluations": [],
        "debate_history": [],
        "sections": {},
        "agent_outputs": {},  # Populated by agents
        "aggregated_scores": {},  # Populated by aggregator
        "current_round": 0,
        "consensus_reached": False,
        "final_report_md": "",
        "metadata": {
            "source": pdf_path,
            "domain": "general",  # Could be extracted or provided
        },
        # Phase 2 new fields
        "evidence_reports": {},  # Populated by evidence_dispatch
        "evidence_report": {},  # Populated by evidence_dispatch (for compatibility)
        "verifier_evidence": {},  # Populated by evidence_dispatch
        "expert_evidence": {},  # Populated by evidence_dispatch
        "reader_evidence": {},  # Populated by evidence_dispatch
    }

    # Create and compile the workflow
    workflow = create_workflow(config)
    app = compile_workflow(workflow, config)

    # Run the workflow
    config_id = {"configurable": {"thread_id": f"eval_{Path(pdf_path).stem}"}}

    logger.info("Running evaluation workflow...")
    final_state = await app.ainvoke(initial_state, config=config_id)

    report = final_state.get("final_report_md", "")

    # Save report - default to output directory
    if output_path is None:
        # Default output path: output/reports/{pdf_name}_{timestamp}.md
        from datetime import datetime, timezone
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        pdf_name = Path(pdf_path).stem
        output_path = f"./output/reports/{pdf_name}_{timestamp}.md"

    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(report, encoding="utf-8")
    logger.info(f"Report saved to: {output_path}")

    return report


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
        "--output",
        help="Path to save the evaluation report",
        default=None,
    )

    parser.add_argument(
        "-v",
        "--verbose",
        help="Enable verbose logging",
        action="store_true",
    )

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger("src").setLevel(logging.DEBUG)

    # Check if PDF file exists
    if not Path(args.pdf_path).exists():
        logger.error(f"PDF file not found: {args.pdf_path}")
        sys.exit(1)

    # Load configuration
    config = None
    if args.config:
        config = load_config(args.config)
        logger.info(f"Loaded configuration from: {args.config}")

    # Run evaluation
    try:
        report = asyncio.run(
            run_evaluation(
                pdf_path=args.pdf_path,
                config=config,
                output_path=args.output,
            )
        )

        print("\n" + "=" * 60)
        print("EVALUATION COMPLETE")
        print("=" * 60)
        # Use safe print to avoid encoding issues on Windows
        try:
            print(report)
        except UnicodeEncodeError:
            # Fallback: write to stdout with errors='replace'
            import sys
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
            print(report)

    except Exception as e:
        logger.error(f"Evaluation failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
