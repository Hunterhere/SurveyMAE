# SurveyMAE Evaluation Script (PowerShell)
#
# Usage:
#   .\run_evaluation.ps1                    # Run default test file
#   .\run_evaluation.ps1 path\to\survey.pdf # Run custom PDF
#   .\run_evaluation.ps1 -o output.md      # Specify output file

# Set encoding to UTF-8 to avoid Windows GBK issues
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

# Default PDF
$PDF_FILE = if ($args.Count -gt 0 -and -not $args[0].StartsWith("-")) { $args[0] } else { "test_paper.pdf" }
$OtherArgs = if ($args.Count -gt 0 -and -not $args[0].StartsWith("-")) { $args[1..($args.Count-1)] } else { $args }

# Run evaluation
uv run python -m src.main $PDF_FILE $OtherArgs
