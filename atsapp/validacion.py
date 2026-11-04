"""Validación del anexo: estructura, formato (XSD) y reglas de negocio."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import IntEnum

from lxml import etree

from .catalogos import Catalogos, rango_periodo
from .documento import Documento, Nodo


class Severidad(IntEnum):
    ERROR = 2
    ADVERTENCIA = 1

    @property
    def texto(self) -> str:
        return "Error" if self is Severidad.ERROR else "Advertencia"


@dataclass(frozen=True)
class Mensaje:
    severidad: Severidad
    ruta: str  # ruta del nodo afectado (ej. /iva/compras/detalleCompras[3]/idProv)
    texto: str
    origen: str = "reglas"  # estructura | xsd | reglas

    @property
    def es_error(self) -> bool:
        return self.severidad is Severidad.ERROR


def validar_nodo(nodo: Nodo, catalogos: Catalogos | None = None, periodo=(None, None)) -> list[Mensaje]:
    """Valida la estructura y el formato de un nodo y su subárbol (sin XSD)."""
    mensajes: list[Mensaje] = []
    _validar(nodo, catalogos, periodo, mensajes)
    return mensajes


def _validar(nodo: Nodo, catalogos, periodo, mensajes: list[Mensaje]) -> None:
    if nodo.desconocido:
        mensajes.append(Mensaje(Severidad.ERROR, nodo.ruta(), f"<{nodo.nombre}> no existe en el esquema del ATS", "estructura"))
        return
    if nodo.es_simple:
        valor = nodo.valor
        if valor == "":
            if nodo.defn.es_obligatorio:
                mensajes.append(Mensaje(Severidad.ERROR, nodo.ruta(), "Campo obligatorio vacío", "estructura"))
            return
        for e in nodo.defn.tipo.errores(valor):
            mensajes.append(Mensaje(Severidad.ERROR, nodo.ruta(), e, "estructura"))
        if catalogos is not None and not nodo.defn.tipo.enumeracion:
            tabla = catalogos.tabla_de(nodo.nombre)
            if tabla is not None:
                fila = tabla.buscar(valor)
                if fila is None:
                    mensajes.append(Mensaje(Severidad.ADVERTENCIA, nodo.ruta(),
                                            f"El código '{valor}' no consta en {tabla.titulo}", "estructura"))
                elif not fila.vigente(*periodo):
                    mensajes.append(Mensaje(Severidad.ADVERTENCIA, nodo.ruta(),
                                            f"El código '{valor}' ({fila.descripcion}) no está vigente en el período", "estructura"))
        return
    # elemento compuesto: verificar cardinalidad de hijos
    for d in nodo.defn.hijos:
        presentes = [h for h in nodo.lista(d.nombre) if not _vacio(h)]
        if len(presentes) < d.min_ocurr:
            mensajes.append(Mensaje(Severidad.ERROR, nodo.ruta(), f"Falta {d.nombre}", "estructura"))
        if d.max_ocurr is not None and len(presentes) > d.max_ocurr:
            mensajes.append(Mensaje(Severidad.ERROR, nodo.ruta(), f"{d.nombre} aparece más de {d.max_ocurr} vez/veces", "estructura"))
    for h in nodo.hijos:
        if not h.defn.es_obligatorio and _vacio(h):
            continue
        _validar(h, catalogos, periodo, mensajes)


def _vacio(n: Nodo) -> bool:
    if n.desconocido:
        return False
    if n.es_simple:
        return n.valor.strip() == ""
    return all(_vacio(h) for h in n.hijos)


_ELEMENTO_EN_MSG = re.compile(r"Element '([^']+)'")


def validar_xsd(doc: Documento) -> list[Mensaje]:
    """Valida el XML que se va a generar contra el esquema oficial."""
    datos = doc.a_bytes(legible=True)
    arbol = etree.fromstring(datos, etree.XMLParser(huge_tree=True))
    esquema = doc.esquema.validador
    esquema.validate(arbol)
    por_linea: dict[int, list] = {}
    for e in arbol.iter():
        por_linea.setdefault(e.sourceline, []).append(e)
    mensajes = []
    for err in esquema.error_log:
        elems = por_linea.get(err.line, [])
        m = _ELEMENTO_EN_MSG.search(err.message)
        elegido = None
        if m:
            elegido = next((e for e in elems if e.tag == m.group(1)), None)
        if elegido is None and elems:
            elegido = elems[0]
        ruta = arbol.getroottree().getpath(elegido) if elegido is not None else "/iva"
        mensajes.append(Mensaje(Severidad.ERROR, ruta, _traducir(err.message), "xsd"))
    return mensajes


def _traducir(msg: str) -> str:
    reemplazos = [
        (r"^Element '([^']+)': ", r"<\1>: "),
        (r"\[facet 'pattern'\] The value '([^']*)' is not accepted by the pattern '([^']*)'\.", r"el valor '\1' no cumple el formato \2."),
        (r"\[facet 'enumeration'\] The value '([^']*)' is not an element of the set \{(.*)\}\.", r"el valor '\1' no está entre los permitidos (\2)."),
        (r"\[facet '(\w+)'\] The value '([^']*)' has a length of '(\d+)'; this differs from the allowed length of '(\d+)'\.",
         r"el valor '\2' tiene \3 caracteres y debe tener \4."),
        (r"This element is not expected\. Expected is one of \( (.*) \)\.", r"este elemento no se esperaba aquí. Se esperaba: \1."),
        (r"This element is not expected\. Expected is \( (.*) \)\.", r"este elemento no se esperaba aquí. Se esperaba: \1."),
        (r"This element is not expected\.", r"este elemento no se esperaba aquí."),
        (r"Missing child element\(s\)\. Expected is one of \( (.*) \)\.", r"faltan elementos. Se esperaba: \1."),
        (r"Missing child element\(s\)\. Expected is \( (.*) \)\.", r"falta el elemento \1."),
        (r"'([^']*)' is not a valid value of the atomic type '([^']*)'\.", r"'\1' no es un valor válido para el tipo \2."),
    ]
    for patron, repl in reemplazos:
        msg = re.sub(patron, repl, msg)
    return msg


def validar_documento(doc: Documento, catalogos: Catalogos | None = None, con_xsd: bool = True) -> list[Mensaje]:
    """Validación completa. Los errores del XSD que repiten uno propio se omiten."""
    from .reglas import aplicar_reglas

    semestral = doc.raiz.texto("regimenMicroempresa") == "SI"
    periodo = rango_periodo(doc.anio, doc.mes, semestral)
    mensajes = validar_nodo(doc.raiz, catalogos, periodo)
    if con_xsd:
        rutas_con_error = {m.ruta for m in mensajes if m.es_error}
        padres_con_error = {r.rsplit("/", 1)[0] for r in rutas_con_error}
        for m in validar_xsd(doc):
            if m.ruta in rutas_con_error or m.ruta in padres_con_error:
                continue
            mensajes.append(m)
    mensajes.extend(aplicar_reglas(doc, catalogos))
    return ordenar(mensajes)


def ordenar(mensajes: list[Mensaje]) -> list[Mensaje]:
    vistos = set()
    unicos = []
    for m in mensajes:
        clave = (m.severidad, m.ruta, m.texto)
        if clave not in vistos:
            vistos.add(clave)
            unicos.append(m)
    return sorted(unicos, key=lambda m: (-int(m.severidad), _clave_ruta(m.ruta)))


def _clave_ruta(ruta: str):
    return [(p.split("[")[0], int(p.split("[")[1].rstrip("]")) if "[" in p else 1) for p in ruta.strip("/").split("/")]
