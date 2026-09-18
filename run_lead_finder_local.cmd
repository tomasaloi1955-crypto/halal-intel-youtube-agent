@echo off
rem Kwork and FL.ru block GitHub servers (403), so they are checked from this PC.
rem Started by Windows Task Scheduler, task "lead_finder_local".
cd /d "%~dp0"
set LEAD_SOURCES=Kwork,FL.ru
set DATA_DIR=%LOCALAPPDATA%\lead_finder
set PYTHONIOENCODING=utf-8
"C:\Users\lima2\AppData\Local\Programs\Python\Python311\python.exe" lead_finder.py >> "%LOCALAPPDATA%\lead_finder\run.log" 2>&1
