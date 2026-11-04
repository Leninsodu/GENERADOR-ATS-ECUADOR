"""Recuerda qué comprobantes de venta ya se sumaron a cada anexo.

En el módulo de ventas del ATS los comprobantes se agrupan por cliente, así que el
anexo no guarda el número de cada factura. Para evitar sumar dos veces la misma venta
se guarda aquí la clave de acceso de cada comprobante importado (al guardar el anexo).
"""

from __future__ import annotations

import json

from . import rutas


def _ruta():
    return rutas.carpeta_datos() / "ventas_importadas.json"


def _cargar() -> dict[str, list[str]]:
    try:
        return json.loads(_ruta().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def clave_anexo(ruc: str, anio: str, mes: str) -> str:
    return f"{ruc}-{anio}-{mes.zfill(2)}"


def importadas(anexo: str) -> set[str]:
    return set(_cargar().get(anexo, []))


def registrar(anexo: str, claves: list[str]) -> None:
    if not claves:
        return
    datos = _cargar()
    actuales = datos.get(anexo, [])
    datos[anexo] = actuales + [c for c in claves if c not in actuales]
    tmp = _ruta().with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(_ruta())
