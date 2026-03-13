#!/bin/bash
# SurveyMAE Evaluation Script
#
# Usage:
#   bash scripts/run_evaluation.sh                    # Run default test file
#   bash scripts/run_evaluation.sh path/to/survey.pdf # Run custom PDF
#   bash scripts/run_evaluation.sh -o output.md      # Specify output file

# Navigate to project root
cd "$(dirname "$0")/.."

# Set Python encoding to avoid Windows GBK issues
export PYTHONIOENCODING=utf-8

# Default PDF
PDF_FILE="${1:-test_survey2.pdf}"
shift || true  # Remove first argument if exists

# Run evaluation
uv run python -m src.main "$PDF_FILE" "$@"
