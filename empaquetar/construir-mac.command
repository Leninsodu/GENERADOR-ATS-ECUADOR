#!/bin/bash
# Construye EditorATS.app en macOS. Requiere Python 3.10 o superior (python.org).
# Doble clic en Finder (la primera vez: clic derecho -> Abrir).
cd "$(dirname "$0")/.." || exit 1
if [ ! -d .venv ]; then python3 -m venv .venv || exit 1; fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install . pyinstaller
.venv/bin/python empaquetar/construir.py
echo
echo "Si todo salió bien, la aplicación está en la carpeta dist: EditorATS.app"
read -r -p "Presione Enter para cerrar"
