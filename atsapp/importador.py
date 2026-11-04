"""Obtiene el esquema at.xsd desde una instalación de DIMM o un plugin del SRI.

Acepta:
  * el archivo at.xsd directamente,
  * el plugin del ATS (ats.plugin.X.zip) que publica el SRI,
  * el JAR ec.gob.sri.dimm.ats.validacion_X.jar,
  * la carpeta de instalación de DIMM (se buscan los JAR en plugins/).
Si hay varias versiones se usa la más reciente. Todo se lee en memoria; no se
extrae nada al disco salvo el at.xsd final.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

from . import rutas

MIEMBRO_XSD = "ec/gob/sri/dimm/ats/validacion/at.xsd"
_JAR_VALIDACION = re.compile(r"ec\.gob\.sri\.dimm\.ats\.validacion_([\d.]+)\.jar$")
_LIMITE_BYTES = 50 * 1024 * 1024


@dataclass
class Encontrado:
    datos: bytes
    origen: str
    version: tuple[int, ...]


def _version(texto: str) -> tuple[int, ...]:
    return tuple(int(x) for x in texto.strip(".").split(".") if x.isdigit())


def _buscar_en_zip(z: zipfile.ZipFile, origen: str, version: tuple[int, ...], profundidad: int) -> list[Encontrado]:
    hallados: list[Encontrado] = []
    for info in z.infolist():
        nombre = info.filename
        if nombre.endswith(MIEMBRO_XSD) and info.file_size < _LIMITE_BYTES:
            hallados.append(Encontrado(z.read(info), f"{origen}!{nombre}", version))
        elif profundidad < 2 and nombre.lower().endswith((".jar", ".zip")) and info.file_size < _LIMITE_BYTES:
            m = _JAR_VALIDACION.search(nombre)
            if m or nombre.lower().endswith(".zip"):
                try:
                    with zipfile.ZipFile(io.BytesIO(z.read(info))) as interno:
                        v = _version(m.group(1)) if m else version
                        hallados += _buscar_en_zip(interno, f"{origen}!{nombre}", v, profundidad + 1)
                except zipfile.BadZipFile:
                    continue
    return hallados


def buscar_esquema(ruta: str | Path) -> Encontrado:
    """Busca at.xsd en la ruta indicada. Lanza FileNotFoundError si no está."""
    ruta = Path(ruta).expanduser()
    hallados: list[Encontrado] = []
    if ruta.is_file() and ruta.suffix.lower() == ".xsd":
        return Encontrado(ruta.read_bytes(), str(ruta), ())
    if ruta.is_file():
        m = _JAR_VALIDACION.search(ruta.name)
        with zipfile.ZipFile(ruta) as z:
            hallados = _buscar_en_zip(z, str(ruta), _version(m.group(1)) if m else (), 0)
    elif ruta.is_dir():
        candidatos = list(ruta.glob("plugins/*.jar")) + list(ruta.glob("*.jar")) + list(ruta.glob("*.zip"))
        for c in candidatos:
            m = _JAR_VALIDACION.search(c.name)
            if not m and "ats" not in c.name.lower():
                continue
            try:
                with zipfile.ZipFile(c) as z:
                    hallados += _buscar_en_zip(z, str(c), _version(m.group(1)) if m else (), 0 if not m else 1)
            except zipfile.BadZipFile:
                continue
        if not hallados:
            for xsd in ruta.glob("**/" + MIEMBRO_XSD):
                hallados.append(Encontrado(xsd.read_bytes(), str(xsd), ()))
    if not hallados:
        raise FileNotFoundError(f"No se encontró el esquema del ATS (at.xsd) en {ruta}")
    return max(hallados, key=lambda h: h.version)


def importar_esquema(ruta: str | Path, destino: Path | None = None) -> Encontrado:
    """Busca el esquema, verifica que se pueda usar y lo copia a la carpeta de datos."""
    from lxml import etree

    from .esquema import Esquema

    encontrado = buscar_esquema(ruta)
    destino = destino or rutas.ruta_esquema_usuario()
    tmp = destino.with_name(destino.name + ".tmp")
    tmp.write_bytes(encontrado.datos)
    try:
        esquema = Esquema(tmp)
        esquema.validador  # compila el XSD completo
        if esquema.raiz.nombre != "iva":
            raise ValueError("El esquema encontrado no corresponde al ATS (raíz distinta de <iva>)")
    except (etree.XMLSchemaParseError, etree.XMLSyntaxError, ValueError):
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(destino)
    (destino.with_suffix(".origen.txt")).write_text(encontrado.origen, encoding="utf-8")
    return encontrado


def ubicaciones_probables() -> list[Path]:
    """Carpetas típicas donde suele estar instalado DIMM."""
    casa = Path.home()
    lista = [casa / "DIMM" / "Dimm", casa / "DIMM", casa / "Dimm"]
    if sys.platform.startswith("win"):
        for var in ("ProgramFiles", "ProgramFiles(x86)", "SystemDrive"):
            base = os.environ.get(var)
            if base:
                lista += [Path(base) / "DIMM", Path(base + "\\") / "DIMM" / "Dimm"]
        lista += [Path("C:/DIMM"), Path("C:/DIMM/Dimm")]
    return [p for p in lista if (p / "plugins").is_dir()]


def copiar_esquema_manual(origen: Path) -> None:
    shutil.copyfile(origen, rutas.ruta_esquema_usuario())
