@echo off
rem Construye EditorATS.exe en Windows. Requiere Python 3.10 o superior (python.org),
rem instalado con la opcion "Add python.exe to PATH".
cd /d "%~dp0\.."
if not exist .venv (
    py -3 -m venv .venv || python -m venv .venv
)
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install . pyinstaller
.venv\Scripts\python empaquetar\construir.py
echo.
echo Si todo salio bien, el programa esta en la carpeta dist: EditorATS.exe
pause
