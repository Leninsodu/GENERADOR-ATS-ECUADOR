"""Modelo en memoria de un anexo ATS y su lectura/escritura en XML."""

from __future__ import annotations

import copy
import zipfile
from pathlib import Path
from typing import Iterator

from lxml import etree

from .esquema import DefElemento, Esquema, TipoSimple

DECLARACION_XML = b'<?xml version="1.0" encoding="UTF-8" standalone="no"?>'


class Nodo:
    """Un elemento del anexo: simple (con valor) o compuesto (con hijos)."""

    def __init__(self, definicion: DefElemento, padre: "Nodo | None" = None, desconocido: bool = False):
        self.defn = definicion
        self.padre = padre
        self.valor: str = ""
        self.hijos: list[Nodo] = []
        self.desconocido = desconocido

    # --- consulta ---------------------------------------------------------
    @property
    def nombre(self) -> str:
        return self.defn.nombre

    @property
    def es_simple(self) -> bool:
        return self.defn.es_simple

    def hijo(self, nombre: str) -> "Nodo | None":
        for h in self.hijos:
            if h.nombre == nombre:
                return h
        return None

    def lista(self, nombre: str) -> list["Nodo"]:
        return [h for h in self.hijos if h.nombre == nombre]

    def texto(self, nombre: str, defecto: str = "") -> str:
        h = self.hijo(nombre)
        return h.valor if h is not None and h.es_simple else defecto

    def buscar(self, ruta: str) -> "Nodo | None":
        """Busca por ruta relativa tipo 'pagoExterior/paisEfecPago'."""
        nodo: Nodo | None = self
        for parte in ruta.split("/"):
            if nodo is None:
                return None
            nodo = nodo.hijo(parte)
        return nodo

    def recorrer(self) -> Iterator["Nodo"]:
        yield self
        for h in self.hijos:
            yield from h.recorrer()

    def indice_entre_iguales(self) -> int:
        """Posición (desde 1) entre los hermanos con el mismo nombre."""
        if self.padre is None:
            return 1
        return self.padre.lista(self.nombre).index(self) + 1

    def ruta(self) -> str:
        """Ruta al estilo XPath, igual a la que genera lxml (getpath)."""
        partes = []
        nodo: Nodo | None = self
        while nodo is not None:
            parte = nodo.nombre
            if nodo.padre is not None and len(nodo.padre.lista(nodo.nombre)) > 1:
                parte += f"[{nodo.indice_entre_iguales()}]"
            partes.append(parte)
            nodo = nodo.padre
        return "/" + "/".join(reversed(partes))

    # --- modificación -----------------------------------------------------
    def poner(self, nombre: str, valor: str) -> "Nodo":
        """Asigna el valor de un hijo simple, creándolo si no existe."""
        h = self.hijo(nombre)
        if h is None:
            h = self.agregar(nombre)
        h.valor = valor
        return h

    def agregar(self, nombre: str, nodo: "Nodo | None" = None) -> "Nodo":
        """Agrega un hijo respetando el orden del esquema."""
        d = self.defn.hijo(nombre)
        if d is None:
            raise KeyError(f"'{nombre}' no es un elemento válido dentro de '{self.nombre}'")
        if nodo is None:
            nodo = crear_vacio(d)
        nodo.padre = self
        orden = self.defn.indice_hijo(nombre)
        pos = len(self.hijos)
        for i, h in enumerate(self.hijos):
            if self.defn.indice_hijo(h.nombre) > orden:
                pos = i
                break
        self.hijos.insert(pos, nodo)
        return nodo

    def insertar_despues(self, referencia: "Nodo", nodo: "Nodo") -> "Nodo":
        nodo.padre = self
        self.hijos.insert(self.hijos.index(referencia) + 1, nodo)
        return nodo

    def reemplazar(self, viejo: "Nodo", nuevo: "Nodo") -> None:
        nuevo.padre = self
        self.hijos[self.hijos.index(viejo)] = nuevo

    def eliminar(self, nodo: "Nodo") -> None:
        self.hijos.remove(nodo)
        nodo.padre = None

    def copiar(self) -> "Nodo":
        padre, self.padre = self.padre, None
        try:
            c = copy.deepcopy(self)
        finally:
            self.padre = padre
        return c


def crear_vacio(defn: DefElemento, padre: Nodo | None = None) -> Nodo:
    """Crea un nodo con todos sus hijos obligatorios (vacíos)."""
    n = Nodo(defn, padre)
    if not defn.es_simple:
        for d in defn.hijos:
            if d.es_obligatorio:
                for _ in range(d.min_ocurr):
                    n.hijos.append(crear_vacio(d, n))
    return n


class Documento:
    """Un anexo ATS completo."""

    def __init__(self, esquema: Esquema, raiz: Nodo | None = None):
        self.esquema = esquema
        self.raiz = raiz if raiz is not None else crear_vacio(esquema.raiz)
        self.avisos_carga: list[str] = []

    # --- datos de cabecera --------------------------------------------------
    @property
    def anio(self) -> int | None:
        try:
            return int(self.raiz.texto("Anio"))
        except ValueError:
            return None

    @property
    def mes(self) -> int | None:
        try:
            return int(self.raiz.texto("Mes"))
        except ValueError:
            return None

    def nombre_sugerido(self, extension: str = ".xml") -> str:
        mes = self.raiz.texto("Mes").zfill(2)
        anio = self.raiz.texto("Anio")
        if extension == ".zip":
            return f"AT{mes}{anio}.zip"
        return f"AT-{mes}{anio}.xml"

    # --- lectura --------------------------------------------------------------
    @classmethod
    def desde_archivo(cls, esquema: Esquema, ruta: str | Path) -> "Documento":
        ruta = Path(ruta)
        if ruta.suffix.lower() == ".zip":
            with zipfile.ZipFile(ruta) as z:
                xmls = [n for n in z.namelist() if n.lower().endswith(".xml")]
                if len(xmls) != 1:
                    raise ValueError("El ZIP debe contener exactamente un archivo XML")
                datos = z.read(xmls[0])
        else:
            datos = ruta.read_bytes()
        return cls.desde_bytes(esquema, datos)

    @classmethod
    def desde_bytes(cls, esquema: Esquema, datos: bytes) -> "Documento":
        parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=True,
                                 remove_pis=True, huge_tree=True)
        xml = etree.fromstring(datos, parser)
        if xml.tag != esquema.raiz.nombre:
            raise ValueError(f"El archivo no es un ATS: la raíz es <{xml.tag}> y se esperaba <{esquema.raiz.nombre}>")
        doc = cls(esquema, Nodo(esquema.raiz))
        doc.raiz = doc._leer(xml, esquema.raiz, None)
        return doc

    def _leer(self, xml, defn: DefElemento, padre: Nodo | None) -> Nodo:
        nodo = Nodo(defn, padre)
        if defn.es_simple:
            nodo.valor = (xml.text or "").strip()
            return nodo
        for hx in xml:
            if not isinstance(hx.tag, str):
                continue
            d = defn.hijo(hx.tag)
            if d is None:
                d = _definicion_desconocida(hx)
                self.avisos_carga.append(f"Elemento no previsto en el esquema: {xml.getroottree().getpath(hx)}")
                h = self._leer(hx, d, nodo)
                h.desconocido = True
            else:
                h = self._leer(hx, d, nodo)
            nodo.hijos.append(h)
        return nodo

    # --- escritura ------------------------------------------------------------
    def a_lxml(self, mapa: dict | None = None):
        """Convierte a un árbol lxml. Si se pasa `mapa`, se llena elemento→Nodo."""
        return _a_lxml(self.raiz, mapa)

    def a_bytes(self, legible: bool = False) -> bytes:
        cuerpo = etree.tostring(self.a_lxml(), encoding="UTF-8", xml_declaration=False, pretty_print=legible)
        return DECLARACION_XML + (b"\n" if legible else b"") + cuerpo

    def guardar_xml(self, ruta: str | Path) -> None:
        _escribir_atomico(Path(ruta), self.a_bytes())

    def guardar_zip(self, ruta: str | Path, nombre_xml: str | None = None) -> None:
        """Guarda el XML comprimido, como pide la ficha técnica (ATmmaaaa.zip)."""
        ruta = Path(ruta)
        nombre_xml = nombre_xml or self.nombre_sugerido(".xml")
        tmp = ruta.with_name(ruta.name + ".tmp")
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr(nombre_xml, self.a_bytes())
        tmp.replace(ruta)


def _a_lxml(nodo: Nodo, mapa: dict | None):
    e = etree.Element(nodo.nombre)
    if mapa is not None:
        mapa[e] = nodo
    if nodo.es_simple:
        e.text = nodo.valor
        return e
    for h in nodo.hijos:
        if _omitible(h):
            continue
        e.append(_a_lxml(h, mapa))
    return e


def _omitible(n: Nodo) -> bool:
    """Los elementos opcionales vacíos no se escriben en el XML."""
    if n.desconocido or n.defn.es_obligatorio:
        return False
    if n.es_simple:
        return n.valor.strip() == ""
    return all(_omitible(h) or (h.es_simple and h.valor.strip() == "") for h in n.hijos)


def _definicion_desconocida(xml) -> DefElemento:
    hijos = [h for h in xml if isinstance(h.tag, str)]
    if not hijos:
        return DefElemento(nombre=xml.tag, min_ocurr=0, tipo=TipoSimple())
    return DefElemento(nombre=xml.tag, min_ocurr=0, hijos=[_definicion_desconocida(h) for h in hijos])


def _escribir_atomico(ruta: Path, datos: bytes) -> None:
    tmp = ruta.with_name(ruta.name + ".tmp")
    tmp.write_bytes(datos)
    tmp.replace(ruta)
