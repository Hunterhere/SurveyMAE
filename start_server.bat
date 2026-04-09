@echo off
echo ========================================
echo SurveyMAE Web Server
echo ========================================
echo.
echo Starting server at: http://localhost:8080
echo Press Ctrl+C to stop
echo.

REM Activate virtual environment and run server
call .venv\Scripts\activate.bat
python -m uvicorn src.web.app:app --reload --port 8000 --host 0.0.0.0 --log-level info

pause
