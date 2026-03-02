@echo off
echo Talk Clash Botini ishga tushirmoqdaman...
if not exist .venv (
    echo [Xatolik] .venv papkasi topilmadi! Birinchi loyihani sozlab oling.
    pause
    exit /b
)
.\.venv\Scripts\python.exe main.py
pause
