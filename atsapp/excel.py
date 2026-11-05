"""Exporta el anexo a un libro de Excel: una hoja de resumen y una hoja por cada tabla del ATS."""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .catalogos import Catalogos
from .documento import Documento, Nodo
from .esquema import DefElemento
from .presentacion import etiqueta

# nombre de la hoja para cada tabla repetible del anexo
NOMBRES_HOJA = {
    "detalleCompras": "Compras",
    "detalleAir": "Compras - Ret. renta",
    "reembolso": "Compras - Reembolsos",
    "detalleVentas": "Ventas",
    "compensacion": "Ventas - Compensaciones",
    "ventaEst": "Ventas por establecimiento",
    "detalleExportaciones": "Exportaciones",
    "detalleAnulados": "Anulados",
}

# hojas que se crean aunque no tengan registros
HOJAS_SIEMPRE = {"detalleCompras", "detalleVentas", "ventaEst", "detalleAnulados"}

# campos que identifican la fila padre en las hojas hijas
CLAVES_PADRE = {
    "detalleCompras": ["idProv", "denoProv", "tipoComprobante", "establecimiento", "puntoEmision", "secuencial"],
    "detalleVentas": ["idCliente", "denoCli", "tipoComprobante"],
}

FORMATO_NUMERO = "#,##0.00"


def _numero(texto: str) -> Decimal:
    try:
        return Decimal(texto.strip() or "0")
    except InvalidOperation:
        return Decimal(0)


class _Tabla:
    def __init__(self, defn: DefElemento, padre: "_Tabla | None"):
        self.defn = defn
        self.padre = padre
        self.columnas: list[tuple[str, DefElemento, bool]] = []  # (ruta relativa, definición, es lista)
        self.hijas: list[_Tabla] = []
        self.filas: list[list] = []
        self._columnas(defn, "")

    def _columnas(self, defn: DefElemento, prefijo: str) -> None:
        for h in defn.hijos:
            ruta = f"{prefijo}{h.nombre}"
            if h.es_simple:
                self.columnas.append((ruta, h, h.es_repetible))
            elif h.es_repetible:
                self.hijas.append(_Tabla(h, self))
            else:
                self._columnas(h, ruta + "/")

    @property
    def hoja(self) -> str:
        return NOMBRES_HOJA.get(self.defn.nombre, etiqueta(self.defn.nombre))[:31]

    def encabezados(self) -> list[str]:
        cab = []
        if self.padre is not None:
            cab.append(f"Nº {etiqueta(self.padre.defn.nombre).lower()}")
            cab += [etiqueta(c) for c in CLAVES_PADRE.get(self.padre.defn.nombre, [])]
        else:
            cab.append("Nº")
        return cab + [etiqueta(r.rsplit("/", 1)[-1]) for r, _d, _l in self.columnas]


def _valor_de(nodo: Nodo, ruta: str, defn: DefElemento, es_lista: bool):
    partes = ruta.split("/")
    actual = nodo
    for p in partes[:-1]:
        actual = actual.hijo(p) if actual is not None else None
    if actual is None:
        return None
    if es_lista:
        return ", ".join(n.valor for n in actual.lista(partes[-1]) if n.valor) or None
    texto = actual.texto(partes[-1])
    if texto == "":
        return None
    if defn.tipo is not None and defn.tipo.base == "decimal":
        return float(_numero(texto))
    # cantidades enteras como número; secuenciales y códigos (con ceros a la izquierda) como texto
    if (defn.tipo is not None and defn.tipo.base == "integer" and "sec" not in defn.nombre.lower()
            and texto.isdigit() and (texto == "0" or not texto.startswith("0"))):
        return int(texto)
    return texto


def _buscar_definiciones(defn: DefElemento) -> list[DefElemento]:
    """Tablas repetibles de primer nivel (las que no están dentro de otra tabla)."""
    if defn.es_simple:
        return []
    if defn.es_repetible:
        return [defn]
    r = []
    for h in defn.hijos:
        r += _buscar_definiciones(h)
    return r


def _llenar(tabla: _Tabla, nodos: list[Nodo], clave_padre: list | None = None) -> None:
    for i, n in enumerate(nodos, 1):
        inicio = list(clave_padre) if clave_padre is not None else [i]
        tabla.filas.append(inicio + [_valor_de(n, r, d, l) for r, d, l in tabla.columnas])
        for hija in tabla.hijas:
            clave = [i] + [n.texto(c) or None for c in CLAVES_PADRE.get(tabla.defn.nombre, [])]
            _llenar(hija, _nodos_de(n, hija.defn), clave)


def _nodos_de(nodo: Nodo, defn: DefElemento) -> list[Nodo]:
    """Todos los nodos con la definición `defn` dentro de `nodo` (atravesando contenedores)."""
    r = []
    for h in nodo.hijos:
        if h.nombre == defn.nombre:
            r.append(h)
        elif not h.es_simple and not h.defn.es_repetible:
            r += _nodos_de(h, defn)
    return r


def _todas(tablas: list[_Tabla]) -> list[_Tabla]:
    r = []
    for t in tablas:
        r.append(t)
        r += _todas(t.hijas)
    return r


# ---------------------------------------------------------------------------------------------
def resumen(doc: Documento, catalogos: Catalogos | None = None) -> list[tuple[str, list[str], list[list]]]:
    """Secciones del resumen: (título, encabezados, filas)."""
    raiz = doc.raiz

    def desc(campo: str, codigo: str) -> str:
        if catalogos is None or not codigo:
            return codigo
        d = catalogos.descripcion(campo, codigo)
        return f"{codigo} - {d}" if d else codigo

    secciones = []
    secciones.append(("Informante", ["Dato", "Valor"], [
        ["RUC", raiz.texto("IdInformante")],
        ["Razón social", raiz.texto("razonSocial")],
        ["Período", f"{raiz.texto('Mes').zfill(2)}/{raiz.texto('Anio')}"],
        ["Establecimientos", raiz.texto("numEstabRuc")],
        ["Total de ventas declarado", float(_numero(raiz.texto("totalVentas")))],
    ]))

    compras = raiz.buscar("compras")
    detalle = compras.lista("detalleCompras") if compras is not None else []
    campos_c = ["baseNoGraIva", "baseImponible", "baseImpGrav", "baseImpExe", "montoIce", "montoIva"]
    ret_iva = ["valRetBien10", "valRetServ20", "valorRetBienes", "valRetServ50", "valorRetServicios",
               "valRetServ100"]
    grupos: dict[str, list] = defaultdict(lambda: [0] + [Decimal(0)] * (len(campos_c) + 2))
    air: dict[str, list] = defaultdict(lambda: [0, Decimal(0), Decimal(0)])
    for c in detalle:
        g = grupos[c.texto("tipoComprobante")]
        g[0] += 1
        for j, campo in enumerate(campos_c, 1):
            g[j] += _numero(c.texto(campo))
        g[len(campos_c) + 1] += sum((_numero(c.texto(x)) for x in ret_iva), Decimal(0))
        for d in _nodos_de(c, doc.esquema.raiz.buscar("detalleAir")):
            a = air[d.texto("codRetAir")]
            a[0] += 1
            a[1] += _numero(d.texto("baseImpAir"))
            a[2] += _numero(d.texto("valRetAir"))
            g[len(campos_c) + 2] += _numero(d.texto("valRetAir"))
    cab_c = ["Tipo de comprobante", "Cantidad"] + [etiqueta(x) for x in campos_c] + ["Retención IVA",
                                                                                     "Retención renta"]
    filas = [[desc("tipoComprobante", k)] + [int(v[0])] + [float(x) for x in v[1:]] for k, v in sorted(grupos.items())]
    if filas:
        filas.append(["TOTAL"] + [sum(f[i] for f in filas) for i in range(1, len(cab_c))])
    secciones.append(("Compras por tipo de comprobante", cab_c, filas))

    filas = [[desc("codRetAir", k), int(v[0]), float(v[1]), float(v[2])] for k, v in sorted(air.items())]
    if filas:
        filas.append(["TOTAL"] + [sum(f[i] for f in filas) for i in range(1, 4)])
    secciones.append(("Retenciones en la fuente (renta) por código",
                      ["Código de retención", "Cantidad", "Base imponible", "Valor retenido"], filas))

    ventas = raiz.buscar("ventas")
    detalle = ventas.lista("detalleVentas") if ventas is not None else []
    campos_v = ["numeroComprobantes", "baseNoGraIva", "baseImponible", "baseImpGrav", "montoIva", "montoIce",
                "valorRetIva", "valorRetRenta"]
    grupos = defaultdict(lambda: [0] + [Decimal(0)] * len(campos_v))
    for v in detalle:
        g = grupos[v.texto("tipoComprobante")]
        g[0] += 1
        for j, campo in enumerate(campos_v, 1):
            g[j] += _numero(v.texto(campo))
    cab_v = ["Tipo de comprobante", "Clientes"] + [etiqueta(x) for x in campos_v]
    filas = [[desc("tipoComprobante", k), int(v[0]), int(v[1])] + [float(x) for x in v[2:]]
             for k, v in sorted(grupos.items())]
    if filas:
        filas.append(["TOTAL"] + [sum(f[i] for f in filas) for i in range(1, len(cab_v))])
    secciones.append(("Ventas por tipo de comprobante", cab_v, filas))

    est = raiz.buscar("ventasEstablecimiento")
    filas = [[e.texto("codEstab"), float(_numero(e.texto("ventasEstab"))), float(_numero(e.texto("ivaComp")))]
             for e in (est.lista("ventaEst") if est is not None else [])]
    if filas:
        filas.append(["TOTAL", sum(f[1] for f in filas), sum(f[2] for f in filas)])
    secciones.append(("Ventas por establecimiento", ["Establecimiento", "Ventas", "IVA compensado"], filas))

    anulados = raiz.buscar("anulados")
    n_anul = len(anulados.lista("detalleAnulados")) if anulados is not None else 0
    exportaciones = raiz.buscar("exportaciones")
    n_exp = len(exportaciones.lista("detalleExportaciones")) if exportaciones is not None else 0
    secciones.append(("Otros", ["Dato", "Cantidad"], [["Exportaciones", n_exp], ["Comprobantes anulados", n_anul]]))
    return secciones


def exportar_xlsx(doc: Documento, ruta: str | Path, catalogos: Catalogos | None = None) -> Path:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    ruta = Path(ruta)
    libro = Workbook()
    negrita = Font(bold=True)
    blanca = Font(bold=True, color="FFFFFF")
    fondo_cab = PatternFill("solid", fgColor="1F3864")
    fondo_sec = PatternFill("solid", fgColor="D9E1F2")
    fondo_total = PatternFill("solid", fgColor="F2F2F2")

    # --- resumen ---
    hoja = libro.active
    hoja.title = "Resumen"
    raiz = doc.raiz
    hoja.append([f"Resumen del ATS {raiz.texto('Mes').zfill(2)}/{raiz.texto('Anio')} — {raiz.texto('razonSocial')}"])
    hoja["A1"].font = Font(bold=True, size=14)
    anchos: dict[int, int] = defaultdict(int)
    for titulo, cab, filas in resumen(doc, catalogos):
        hoja.append([])
        hoja.append([titulo])
        hoja.cell(hoja.max_row, 1).font = Font(bold=True, size=12)
        hoja.append(cab)
        for j in range(1, len(cab) + 1):
            celda = hoja.cell(hoja.max_row, j)
            celda.font, celda.fill = blanca, fondo_cab
            celda.alignment = Alignment(wrap_text=True, vertical="center")
        if not filas:
            hoja.append(["(sin registros)"])
            continue
        for f in filas:
            hoja.append(f)
            for j, v in enumerate(f, 1):
                celda = hoja.cell(hoja.max_row, j)
                if isinstance(v, float):
                    celda.number_format = FORMATO_NUMERO
                if f[0] == "TOTAL":
                    celda.font, celda.fill = negrita, fondo_total
                anchos[j] = max(anchos[j], len(str(v)) if not isinstance(v, float) else 14)
    for j, a in anchos.items():
        hoja.column_dimensions[get_column_letter(j)].width = min(max(a + 2, 14), 60)

    # --- informante ---
    hoja = libro.create_sheet("Informante")
    hoja.append(["Campo", "Valor"])
    for h in doc.esquema.raiz.hijos:
        if h.es_simple:
            hoja.append([etiqueta(h.nombre), raiz.texto(h.nombre)])
    _formato_tabla(hoja, fondo_cab, blanca)

    # --- una hoja por tabla ---
    tablas = [_Tabla(d, None) for d in _buscar_definiciones(doc.esquema.raiz)]
    for t in tablas:
        _llenar(t, _nodos_de(raiz, t.defn))
    for t in _todas(tablas):
        if not t.filas and (t.padre is not None or t.defn.nombre not in HOJAS_SIEMPRE):
            continue
        hoja = libro.create_sheet(t.hoja)
        hoja.append(t.encabezados())
        for f in t.filas:
            hoja.append(f)
        for fila in hoja.iter_rows(min_row=2):
            for celda in fila:
                if isinstance(celda.value, float):
                    celda.number_format = FORMATO_NUMERO
        if not t.filas:
            hoja.append(["(sin registros)"])
        _formato_tabla(hoja, fondo_cab, blanca)

    ruta.parent.mkdir(parents=True, exist_ok=True)
    libro.save(ruta)
    return ruta


def _formato_tabla(hoja, fondo, fuente) -> None:
    from openpyxl.utils import get_column_letter

    for celda in hoja[1]:
        celda.fill, celda.font = fondo, fuente
    hoja.freeze_panes = "B2"
    if hoja.max_row > 1:
        hoja.auto_filter.ref = hoja.dimensions
    for j, col in enumerate(hoja.iter_cols(min_row=1, max_row=min(hoja.max_row, 300)), 1):
        largo = max((len(str(c.value)) for c in col if c.value is not None), default=8)
        hoja.column_dimensions[get_column_letter(j)].width = min(max(largo + 2, 10), 50)
