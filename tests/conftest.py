"""Datos de prueba.

El esquema oficial (at.xsd) no se incluye en el proyecto: se importa desde el
plugin del ATS del SRI. Ruta configurable con ATSAPP_PLUGIN_ATS; por defecto se
busca ../ats.plugin.*.zip junto al proyecto. Las pruebas con un anexo real usan
la variable ATSAPP_ANEXO_REAL (ruta a un AT-mmaaaa.xml) y se omiten si no está definida.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from atsapp import importador
from atsapp.catalogos import Catalogos
from atsapp.esquema import Esquema

RAIZ = Path(__file__).resolve().parents[2]


def _plugin() -> Path | None:
    if os.environ.get("ATSAPP_PLUGIN_ATS"):
        return Path(os.environ["ATSAPP_PLUGIN_ATS"])
    candidatos = sorted(RAIZ.glob("ats.plugin.*.zip"))
    return candidatos[-1] if candidatos else None


@pytest.fixture(scope="session")
def ruta_xsd() -> Path:
    """El esquema incluido con el programa (no se necesita DIMM)."""
    from atsapp import rutas

    return rutas.ruta_esquema_incluido()


@pytest.fixture(scope="session")
def plugin_ats() -> Path:
    plugin = _plugin()
    if plugin is None or not plugin.exists():
        pytest.skip("No se encontró el plugin del ATS")
    return plugin


@pytest.fixture(scope="session")
def esquema(ruta_xsd) -> Esquema:
    return Esquema(ruta_xsd)


@pytest.fixture(scope="session")
def catalogos(tmp_path_factory) -> Catalogos:
    return Catalogos.cargar(extra=tmp_path_factory.mktemp("sin_extra") / "no_existe.yaml")


@pytest.fixture(scope="session")
def anexo_real() -> Path:
    ruta = Path(os.environ.get("ATSAPP_ANEXO_REAL", "/no-configurado"))
    if not ruta.exists():
        pytest.skip("No hay un anexo real para probar")
    return ruta
