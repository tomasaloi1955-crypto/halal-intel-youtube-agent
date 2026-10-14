@echo off
rem Double-click: authorizes the Tamra School YouTube channel and copies the token to clipboard.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
chcp 65001 >nul
"C:\Users\lima2\AppData\Local\Programs\Python\Python311\python.exe" tamra_youtube_auth.py
pause
