#!/bin/bash
# Construye el ejecutable EditorATS en Linux. Requiere python3 y python3-venv.
cd "$(dirname "$0")/.." || exit 1
if [ ! -d .venv ]; then python3 -m venv .venv || exit 1; fi
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install . pyinstaller
.venv/bin/python empaquetar/construir.py
