"""Lectura del esquema XSD del ATS.

La aplicación no trae el esquema del SRI incorporado: lo lee en tiempo de
ejecución (importado desde una instalación de DIMM o desde el archivo at.xsd).
A partir del esquema se obtiene la estructura del anexo: qué elementos hay, en
qué orden, cuáles son obligatorios o repetibles y qué restricciones tiene cada
valor. La interfaz y el XML de salida se generan desde esa estructura.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import etree

XS = "{http://www.w3.org/2001/XMLSchema}"

_DECIMAL_RE = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)")
_ENTERO_RE = re.compile(r"[+-]?\d+")


@dataclass
class TipoSimple:
    """Tipo de un valor de texto con sus restricciones (facetas XSD)."""

    nombre: str | None = None
    base: str = "string"  # string | decimal | integer
    enumeracion: list[str] = field(default_factory=list)
    # Cada paso de derivación aporta un grupo de patrones: dentro de un grupo
    # basta con cumplir uno; deben cumplirse todos los grupos.
    patrones: list[list[str]] = field(default_factory=list)
    longitud: int | None = None
    min_longitud: int | None = None
    max_longitud: int | None = None
    min_incl: Decimal | None = None
    max_incl: Decimal | None = None
    min_excl: Decimal | None = None
    max_excl: Decimal | None = None
    total_digitos: int | None = None
    decimales: int | None = None
    colapsar_espacios: bool = False

    @property
    def es_numerico(self) -> bool:
        return self.base in ("decimal", "integer")

    def normalizar(self, valor: str) -> str:
        if self.colapsar_espacios:
            return " ".join(valor.split())
        return valor

    def errores(self, valor: str) -> list[str]:
        """Devuelve los problemas del valor (lista vacía si es válido)."""
        v = self.normalizar(valor)
        errores: list[str] = []
        if self.enumeracion and v not in self.enumeracion:
            errores.append("Valor no permitido. Opciones: " + ", ".join(self.enumeracion))
            return errores
        if self.longitud is not None and len(v) != self.longitud:
            errores.append(f"Debe tener exactamente {self.longitud} caracteres")
        if self.min_longitud is not None and len(v) < self.min_longitud:
            errores.append(f"Debe tener al menos {self.min_longitud} caracteres")
        if self.max_longitud is not None and len(v) > self.max_longitud:
            errores.append(f"Debe tener como máximo {self.max_longitud} caracteres")
        for grupo in self.patrones:
            if not any(re.fullmatch(p, v) for p in grupo):
                errores.append(_describir_patron(grupo))
                break
        if self.es_numerico:
            errores.extend(self._errores_numericos(v))
        return errores

    def _errores_numericos(self, v: str) -> list[str]:
        patron = _ENTERO_RE if self.base == "integer" else _DECIMAL_RE
        if not patron.fullmatch(v):
            return ["Debe ser un número" + (" entero" if self.base == "integer" else "")]
        try:
            n = Decimal(v)
        except InvalidOperation:
            return ["Número no válido"]
        errores = []
        if self.min_incl is not None and n < self.min_incl:
            errores.append(f"Debe ser mayor o igual a {self.min_incl}")
        if self.max_incl is not None and n > self.max_incl:
            errores.append(f"Debe ser menor o igual a {self.max_incl}")
        if self.min_excl is not None and n <= self.min_excl:
            errores.append(f"Debe ser mayor a {self.min_excl}")
        if self.max_excl is not None and n >= self.max_excl:
            errores.append(f"Debe ser menor a {self.max_excl}")
        entero, _, frac = v.lstrip("+-").partition(".")
        frac = frac.rstrip("0")
        if self.decimales is not None and len(frac) > self.decimales:
            errores.append(f"Máximo {self.decimales} decimales")
        if self.total_digitos is not None and len(entero.lstrip("0")) + len(frac) > self.total_digitos:
            errores.append(f"Máximo {self.total_digitos} dígitos en total")
        return errores

    @property
    def es_fecha(self) -> bool:
        return any("[/]" in p or "/" in p for g in self.patrones for p in g)


def _describir_patron(grupo: list[str]) -> str:
    texto = " | ".join(grupo)
    if "[/]" in texto:
        return "Fecha no válida; use el formato dd/mm/aaaa"
    if "\\.[0-9]{2}" in texto:
        return "Monto no válido; use punto decimal y máximo 2 decimales (ej. 1234.56)"
    m = re.fullmatch(r"\\d\{(\d+)\}|\[0-9\]\{(\d+)\}", texto)
    if m:
        return f"Debe tener exactamente {m.group(1) or m.group(2)} dígitos"
    m = re.fullmatch(r"\\d\{(\d+),(\d+)\}|\[0-9\]\{(\d+),(\d+)\}", texto)
    if m:
        a, b = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        return f"Debe tener entre {a} y {b} dígitos"
    return f"Formato no válido (patrón esperado: {texto})"


@dataclass
class DefElemento:
    """Definición de un elemento del anexo según el esquema."""

    nombre: str
    min_ocurr: int = 1
    max_ocurr: int | None = 1  # None = ilimitado
    tipo: TipoSimple | None = None  # None = elemento compuesto
    hijos: list["DefElemento"] = field(default_factory=list)
    documentacion: str = ""

    @property
    def es_simple(self) -> bool:
        return self.tipo is not None

    @property
    def es_repetible(self) -> bool:
        return self.max_ocurr is None or self.max_ocurr > 1

    @property
    def es_obligatorio(self) -> bool:
        return self.min_ocurr > 0

    def hijo(self, nombre: str) -> "DefElemento | None":
        for h in self.hijos:
            if h.nombre == nombre:
                return h
        return None

    def indice_hijo(self, nombre: str) -> int:
        for i, h in enumerate(self.hijos):
            if h.nombre == nombre:
                return i
        return len(self.hijos)

    def buscar(self, nombre: str) -> "DefElemento | None":
        """Busca un elemento por nombre en todo el subárbol."""
        if self.nombre == nombre:
            return self
        for h in self.hijos:
            r = h.buscar(nombre)
            if r is not None:
                return r
        return None


class Esquema:
    """Esquema del ATS cargado desde un archivo XSD."""

    def __init__(self, ruta: str | Path):
        self.ruta = Path(ruta)
        self._arbol = etree.parse(str(self.ruta))
        raiz = self._arbol.getroot()
        self._simples = {e.get("name"): e for e in raiz.findall(XS + "simpleType")}
        self._complejos = {e.get("name"): e for e in raiz.findall(XS + "complexType")}
        self._cache_simples: dict[str, TipoSimple] = {}
        elementos = raiz.findall(XS + "element")
        if not elementos:
            raise ValueError("El esquema no declara ningún elemento raíz")
        self.raiz: DefElemento = self._elemento(elementos[0], profundidad=0)
        self._validador: etree.XMLSchema | None = None

    @property
    def validador(self) -> etree.XMLSchema:
        if self._validador is None:
            self._validador = etree.XMLSchema(self._arbol)
        return self._validador

    # --- construcción -----------------------------------------------------
    def _elemento(self, nodo, profundidad: int) -> DefElemento:
        if profundidad > 30:
            raise ValueError("Esquema demasiado profundo o recursivo")
        max_txt = nodo.get("maxOccurs", "1")
        d = DefElemento(
            nombre=nodo.get("name"),
            min_ocurr=int(nodo.get("minOccurs", "1")),
            max_ocurr=None if max_txt == "unbounded" else int(max_txt),
            documentacion=_documentacion(nodo),
        )
        tipo = nodo.get("type")
        simple_inline = nodo.find(XS + "simpleType")
        complejo_inline = nodo.find(XS + "complexType")
        if tipo is not None:
            nombre = _local(tipo)
            if tipo.startswith("xsd:") or tipo.startswith("xs:"):
                d.tipo = TipoSimple(base=_base_builtin(nombre))
            elif nombre in self._simples:
                d.tipo = self._tipo_simple_nombrado(nombre)
            elif nombre in self._complejos:
                d.hijos = self._hijos_complejo(self._complejos[nombre], profundidad)
            else:
                raise ValueError(f"Tipo no encontrado en el esquema: {tipo}")
        elif simple_inline is not None:
            d.tipo = self._tipo_simple(simple_inline)
        elif complejo_inline is not None:
            d.hijos = self._hijos_complejo(complejo_inline, profundidad)
        else:
            d.tipo = TipoSimple()
        return d

    def _hijos_complejo(self, nodo, profundidad: int) -> list[DefElemento]:
        hijos: list[DefElemento] = []
        contenido = nodo.find(XS + "complexContent")
        if contenido is not None:
            ext = contenido.find(XS + "extension")
            if ext is None:
                raise ValueError("Solo se admite complexContent/extension")
            base = _local(ext.get("base"))
            hijos.extend(self._hijos_complejo(self._complejos[base], profundidad))
            nodo = ext
        secuencia = nodo.find(XS + "sequence")
        if secuencia is not None:
            for e in secuencia:
                if e.tag == XS + "element":
                    hijos.append(self._elemento(e, profundidad + 1))
                elif e.tag in (XS + "choice", XS + "all", XS + "group", XS + "any"):
                    raise ValueError(f"Construcción XSD no soportada: {_local(e.tag)}")
        return hijos

    def _tipo_simple_nombrado(self, nombre: str) -> TipoSimple:
        if nombre not in self._cache_simples:
            t = self._tipo_simple(self._simples[nombre])
            t.nombre = nombre
            self._cache_simples[nombre] = t
        return copy.deepcopy(self._cache_simples[nombre])

    def _tipo_simple(self, nodo) -> TipoSimple:
        restr = nodo.find(XS + "restriction")
        if restr is None:
            return TipoSimple()
        base = restr.get("base", "xsd:string")
        nombre_base = _local(base)
        if nombre_base in self._simples and not base.startswith(("xsd:", "xs:")):
            t = self._tipo_simple_nombrado(nombre_base)
            t.nombre = None
        else:
            t = TipoSimple(base=_base_builtin(nombre_base))
        patrones: list[str] = []
        enumeracion: list[str] = []
        for f in restr:
            if not isinstance(f.tag, str):
                continue
            faceta, valor = _local(f.tag), f.get("value")
            if faceta == "pattern":
                patrones.append(valor)
            elif faceta == "enumeration":
                enumeracion.append(valor)
            elif faceta == "length":
                t.longitud = int(valor)
            elif faceta == "minLength":
                t.min_longitud = int(valor)
            elif faceta == "maxLength":
                t.max_longitud = int(valor)
            elif faceta == "minInclusive":
                t.min_incl = Decimal(valor)
            elif faceta == "maxInclusive":
                t.max_incl = Decimal(valor)
            elif faceta == "minExclusive":
                t.min_excl = Decimal(valor)
            elif faceta == "maxExclusive":
                t.max_excl = Decimal(valor)
            elif faceta == "totalDigits":
                t.total_digitos = int(valor)
            elif faceta == "fractionDigits":
                t.decimales = int(valor)
            elif faceta == "whiteSpace":
                t.colapsar_espacios = valor == "collapse"
        if patrones:
            t.patrones.append(patrones)
        if enumeracion:
            t.enumeracion = enumeracion
        return t


def _local(nombre: str) -> str:
    if "}" in nombre:
        return nombre.split("}", 1)[1]
    return nombre.split(":", 1)[-1]


def _base_builtin(nombre: str) -> str:
    if nombre in ("decimal", "double", "float"):
        return "decimal"
    if nombre in ("integer", "int", "long", "short", "positiveInteger", "nonNegativeInteger"):
        return "integer"
    return "string"


def _documentacion(nodo) -> str:
    docs = nodo.findall(f"{XS}annotation/{XS}documentation")
    docs += nodo.findall(f"{XS}simpleType/{XS}annotation/{XS}documentation")
    textos = [d.text.strip() for d in docs if d.text and d.text.strip()]
    return " ".join(" ".join(t.split()) for t in textos)
