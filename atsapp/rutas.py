"""Carpetas de datos del usuario según el sistema operativo."""

from __future__ import annotations

import os
import sys
from pathlib import Path

NOMBRE_APP = "atsapp"


def carpeta_datos() -> Path:
    """Carpeta donde se guardan el esquema y los catálogos importados.

    Se puede forzar con la variable de entorno ATSAPP_DATOS.
    """
    forzada = os.environ.get("ATSAPP_DATOS")
    if forzada:
        base = Path(forzada)
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / NOMBRE_APP
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / NOMBRE_APP
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / NOMBRE_APP
    base.mkdir(parents=True, exist_ok=True)
    return base


def ruta_esquema_usuario() -> Path:
    """Esquema importado por el usuario (para actualizarlo sin reinstalar el programa)."""
    return carpeta_datos() / "at.xsd"


def ruta_esquema_incluido() -> Path:
    """Esquema que viene con el programa."""
    from importlib import resources

    return Path(str(resources.files("atsapp").joinpath("datos/at.xsd")))


def ruta_esquema() -> Path:
    """Esquema en uso: el importado por el usuario si existe; si no, el incluido."""
    propio = ruta_esquema_usuario()
    return propio if propio.is_file() else ruta_esquema_incluido()


def ruta_catalogos() -> Path:
    return carpeta_datos() / "catalogos.sqlite"
