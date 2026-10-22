@echo off
cd /d "%~dp0"
python -m pip install -q -r requirements.txt
:start
python bot.py
echo Bot stopped, restarting in 10 seconds... (close this window to stop it)
timeout /t 10 /nobreak >nul
goto start
