# SurveyMAE Evaluation Script (PowerShell)
#
# Usage:
#   .\run_evaluation.ps1                              # Run default test file
#   .\run_evaluation.ps1 "path\to\survey.pdf"      # Run custom PDF (use quotes for paths with spaces)
#   .\run_evaluation.ps1 -c config/custom.yaml         # Specify config file

# Set encoding to UTF-8 to avoid Windows GBK issues
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

# Parse arguments more robustly
$PDF_FILE = $null
$OtherArgs = @()

for ($i = 0; $i -lt $args.Count; $i++) {
    $arg = $args[$i]
    if ($arg -eq "-h" -or $arg -eq "--help") {
        # Pass through help flag
        $OtherArgs += $arg
    } elseif ($arg -eq "-c" -or $arg -eq "--config") {
        # Capture config flag and its value
        $OtherArgs += $arg
        if ($i + 1 -lt $args.Count) {
            $i++
            $OtherArgs += $args[$i]
        }
    } elseif ($arg -match "^-") {
        # Other flags
        $OtherArgs += $arg
    } elseif ($PDF_FILE -eq $null) {
        # First non-flag argument is the PDF file
        $PDF_FILE = $arg
    } else {
        # Additional arguments
        $OtherArgs += $arg
    }
}

# Use default if no PDF provided
if ($PDF_FILE -eq $null) {
    $PDF_FILE = "test_paper.pdf"
}

# Run evaluation - wrap PDF_FILE in quotes for paths with spaces
Write-Host "Running: $PDF_FILE" -ForegroundColor Cyan
uv run python -m src.main "$PDF_FILE" @OtherArgs
