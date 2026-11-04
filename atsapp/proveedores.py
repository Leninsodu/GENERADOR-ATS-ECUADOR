"""Memoria local de nombres de proveedores (el ATS solo guarda el RUC)."""

from __future__ import annotations

import json

from . import rutas

_cache: dict[str, str] | None = None


def _ruta():
    return rutas.carpeta_datos() / "proveedores.json"


def todos() -> dict[str, str]:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(_ruta().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _cache = {}
    return _cache


def nombre(identificacion: str) -> str:
    return todos().get(identificacion, "")


def recordar(nombres: dict[str, str]) -> None:
    datos = todos()
    cambios = {k: v for k, v in nombres.items() if k and v and datos.get(k) != v}
    if not cambios:
        return
    datos.update(cambios)
    tmp = _ruta().with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    tmp.replace(_ruta())
