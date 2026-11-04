"""Textos legibles para los elementos del anexo."""

from __future__ import annotations

import re
from functools import lru_cache
from importlib import resources

import yaml

from .esquema import DefElemento


@lru_cache(maxsize=1)
def _datos() -> dict:
    texto = resources.files("atsapp").joinpath("datos/presentacion.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(texto) or {}


def etiqueta(nombre: str) -> str:
    texto = (_datos().get("etiquetas") or {}).get(nombre)
    if texto:
        return texto
    # camelCase -> "Camel case"
    partes = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", nombre).lower()
    return partes[:1].upper() + partes[1:]


def etiqueta_corta(nombre: str) -> str:
    return (_datos().get("cortas") or {}).get(nombre) or etiqueta(nombre)


def columnas(defn: DefElemento) -> list[DefElemento]:
    nombres = (_datos().get("columnas") or {}).get(defn.nombre)
    if nombres:
        cols = [defn.hijo(n) for n in nombres]
        return [c for c in cols if c is not None]
    return [h for h in defn.hijos if h.es_simple][:8]


def columnas_total(defn: DefElemento) -> list[str]:
    return list((_datos().get("totales") or {}).get(defn.nombre) or [])


_PARTE = re.compile(r"([^\[]+)(?:\[(\d+)\])?")


def describir_ruta(ruta: str) -> str:
    """'/iva/compras/detalleCompras[5]/idProv' -> 'Compra 5 › Identificación del proveedor'."""
    partes = [p for p in ruta.strip("/").split("/") if p][1:]  # sin la raíz
    textos = []
    for i, p in enumerate(partes):
        m = _PARTE.fullmatch(p)
        nombre, indice = m.group(1), m.group(2)
        # el contenedor (compras) se omite si le sigue su detalle
        if i + 1 < len(partes) and nombre in ("compras", "ventas", "ventasEstablecimiento", "exportaciones",
                                              "recap", "fideicomisos", "anulados", "rendFinancieros",
                                              "air", "reembolsos", "formasDePago", "compensaciones"):
            continue
        texto = etiqueta(nombre)
        if indice:
            texto += f" {indice}"
        elif nombre.startswith("detalle") or nombre in ("ventaEst", "reembolso", "compensacion"):
            texto += " 1"
        textos.append(texto)
    return " › ".join(textos) if textos else "Anexo"
