#!/usr/bin/env python3
"""SurveyMAE Web Server Launcher with auto-reload"""

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent

def main():
    print("=" * 60)
    print("SurveyMAE Web Server")
    print("=" * 60)
    print("\nStarting server at: http://localhost:8000")
    print("Press Ctrl+C to stop\n")

    cmd = [
        sys.executable, "-m", "uvicorn",
        "src.web.app:app",
        "--reload",
        "--port", "8000",
        "--host", "0.0.0.0",
        "--log-level", "info"
    ]

    try:
        subprocess.run(cmd, cwd=HERE)
    except KeyboardInterrupt:
        print("\n\nServer stopped.")

if __name__ == "__main__":
    main()
