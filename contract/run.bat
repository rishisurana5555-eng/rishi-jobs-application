@echo off
REM Rishi Jobs Contract Generator - starts the Flask API and the Streamlit app
cd /d "%~dp0"
start "Rishi Jobs Contract API" cmd /k python api.py
timeout /t 2 /nobreak >nul
python -m streamlit run app.py
