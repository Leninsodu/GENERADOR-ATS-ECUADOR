"""Punto de entrada para el ejecutable (PyInstaller necesita un script sin imports relativos)."""

import sys

from atsapp.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
