"""Catálogos de códigos del ATS (tablas de la ficha técnica)."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

import yaml

from . import rutas


@dataclass
class Fila:
    codigo: str
    descripcion: str
    desde: dt.date | None = None
    hasta: dt.date | None = None
    extra: list = field(default_factory=list)

    def vigente(self, inicio: dt.date | None, fin: dt.date | None) -> bool:
        """¿Estuvo vigente en algún momento entre inicio y fin?"""
        if inicio is None or fin is None:
            return True
        if self.desde and self.desde > fin:
            return False
        if self.hasta and self.hasta < inicio:
            return False
        return True


@dataclass
class Tabla:
    clave: str
    titulo: str
    filas: list[Fila]

    def buscar(self, codigo: str) -> Fila | None:
        for f in self.filas:
            if f.codigo == codigo:
                return f
        return None

    def vigentes(self, inicio: dt.date | None, fin: dt.date | None) -> list[Fila]:
        return [f for f in self.filas if f.vigente(inicio, fin)]


class Catalogos:
    def __init__(self, datos: dict):
        self.tablas: dict[str, Tabla] = {}
        for clave, t in (datos.get("tablas") or {}).items():
            filas = []
            for fila in t.get("filas") or []:
                fila = list(fila) + [None] * (4 - len(fila))
                filas.append(Fila(str(fila[0]), str(fila[1]), _fecha(fila[2]), _fecha(fila[3]), list(fila[4:])))
            self.tablas[clave] = Tabla(clave, t.get("titulo", clave), filas)
        self.campos: dict[str, str] = dict(datos.get("campos") or {})
        self.tarifas_iva: list[tuple[int, dt.date | None, dt.date | None]] = [
            (int(t[0]), _fecha(t[1]), _fecha(t[2])) for t in datos.get("tarifas_iva") or []
        ]

    @classmethod
    def cargar(cls, extra: Path | None = None) -> "Catalogos":
        """Carga los catálogos incluidos y, si existe, los del usuario encima."""
        texto = resources.files("atsapp").joinpath("datos/catalogos.yaml").read_text(encoding="utf-8")
        datos = yaml.safe_load(texto)
        extra = extra if extra is not None else rutas.carpeta_datos() / "catalogos.yaml"
        if extra.is_file():
            propio = yaml.safe_load(extra.read_text(encoding="utf-8")) or {}
            datos.setdefault("tablas", {}).update(propio.get("tablas") or {})
            datos.setdefault("campos", {}).update(propio.get("campos") or {})
            if propio.get("tarifas_iva"):
                datos["tarifas_iva"] = propio["tarifas_iva"]
        return cls(datos)

    def tabla_de(self, campo: str) -> Tabla | None:
        clave = self.campos.get(campo)
        return self.tablas.get(clave) if clave else None

    def descripcion(self, campo: str, codigo: str) -> str | None:
        t = self.tabla_de(campo)
        if t is None:
            return None
        f = t.buscar(codigo)
        return f.descripcion if f else None

    def tarifas_en(self, fecha: dt.date) -> list[int]:
        return [t for t, d, h in self.tarifas_iva if (d is None or d <= fecha) and (h is None or h >= fecha)]


def _fecha(v) -> dt.date | None:
    if v is None or v == "":
        return None
    if isinstance(v, dt.date):
        return v
    return dt.date.fromisoformat(str(v))


def rango_periodo(anio: int | None, mes: int | None, semestral: bool = False) -> tuple[dt.date | None, dt.date | None]:
    """Primer y último día del período declarado."""
    if not anio or not mes or not 1 <= mes <= 12:
        return None, None
    mes_inicio = mes - 5 if semestral and mes in (6, 12) else mes
    inicio = dt.date(anio, mes_inicio, 1)
    fin = (dt.date(anio + (mes == 12), mes % 12 + 1, 1)) - dt.timedelta(days=1)
    return inicio, fin
