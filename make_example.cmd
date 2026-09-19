@echo off
rem Double-click: asks for a Telegram channel link, writes 3 example posts + a message to the owner.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
chcp 65001 >nul
"C:\Users\lima2\AppData\Local\Programs\Python\Python311\python.exe" example_generator.py
pause
