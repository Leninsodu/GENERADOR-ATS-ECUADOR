"""Comprobantes de retención electrónicos y su registro en el ATS.

* Retención RECIBIDA (un cliente le retuvo al informante): se suma en valorRetIva /
  valorRetRenta del registro de ventas de ese cliente.
* Retención EMITIDA (el informante retuvo a un proveedor): se registra en la compra
  que sustenta: IVA por porcentaje (10, 20, 30, 50, 70, 100 %), renta en el detalle AIR
  y los datos del comprobante de retención (serie, secuencial, autorización, fecha).

Se leen los XML del SRI (versiones 1.0.0 y 2.0.0) y también el PDF (RIDE).
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal

from .documento import Documento, Nodo, crear_vacio

RENTA, IVA, ISD = "1", "2", "6"
CAMPO_IVA_POR_PORCENTAJE = {
    Decimal(10): "valRetBien10", Decimal(20): "valRetServ20", Decimal(30): "valorRetBienes",
    Decimal(50): "valRetServ50", Decimal(70): "valorRetServicios", Decimal(100): "valRetServ100",
}
# Tabla 11 de la ficha: código de retención de IVA por porcentaje
CODIGO_IVA_POR_PORCENTAJE = {Decimal(10): "9", Decimal(20): "10", Decimal(30): "1", Decimal(50): "11",
                             Decimal(70): "2", Decimal(100): "3"}
TIPO_VENTA_POR_SUSTENTO = {"01": "18", "04": "04", "05": "05"}


@dataclass
class LineaRetencion:
    impuesto: str  # 1 renta, 2 IVA, 6 ISD
    codigo: str
    base: Decimal
    porcentaje: Decimal
    valor: Decimal
    cod_doc_sustento: str = ""
    num_doc_sustento: str = ""  # 15 dígitos: establecimiento + punto + secuencial
    fecha_doc_sustento: dt.date | None = None
    codigo_leido: str | None = None  # código tal como vino en el comprobante (None = no aplica)

    def __post_init__(self) -> None:
        if self.codigo_leido is None:
            self.codigo_leido = self.codigo

    @property
    def serie_sustento(self) -> tuple[str, str, str]:
        n = re.sub(r"\D", "", self.num_doc_sustento)
        if len(n) >= 7:
            return n[:3], n[3:6], n[6:]
        return "", "", ""


@dataclass
class Retencion:
    archivo: str
    origen: str = "xml"
    ambiente: str = ""
    estado: str = ""
    ruc_agente: str = ""
    razon_agente: str = ""
    estab: str = ""
    pto_emi: str = ""
    secuencial: str = ""
    clave_acceso: str = ""
    numero_autorizacion: str = ""
    fecha_emision: dt.date | None = None
    tipo_id_retenido: str = ""
    id_retenido: str = ""
    razon_retenido: str = ""
    periodo_fiscal: str = ""  # mm/aaaa
    lineas: list[LineaRetencion] = field(default_factory=list)
    avisos_lectura: list[str] = field(default_factory=list)

    @property
    def numero(self) -> str:
        return f"{self.estab}-{self.pto_emi}-{self.secuencial}"

    @property
    def autorizacion(self) -> str:
        return self.numero_autorizacion or self.clave_acceso

    @property
    def total_iva(self) -> Decimal:
        return sum((l.valor for l in self.lineas if l.impuesto == IVA), Decimal(0))

    @property
    def total_renta(self) -> Decimal:
        return sum((l.valor for l in self.lineas if l.impuesto == RENTA), Decimal(0))

    @property
    def total(self) -> Decimal:
        return sum((l.valor for l in self.lineas), Decimal(0))

    def documentos(self) -> list[tuple[str, str]]:
        """(código, número) de los documentos sustento, sin repetir."""
        vistos: list[tuple[str, str]] = []
        for l in self.lineas:
            k = (l.cod_doc_sustento, l.num_doc_sustento)
            if k not in vistos:
                vistos.append(k)
        return vistos


# --- lectura XML -------------------------------------------------------------------------
def desde_xml(raiz, nombre: str, estado: str = "", numero_autorizacion: str = "") -> Retencion:
    from .comprobantes import ErrorComprobante, _dec, _fecha, _hijo, _local, _texto

    r = Retencion(archivo=nombre, estado=estado, numero_autorizacion=numero_autorizacion)
    it = _hijo(raiz, "infoTributaria")
    info = _hijo(raiz, "infoCompRetencion")
    if it is None or info is None:
        raise ErrorComprobante("Comprobante de retención incompleto")
    r.ambiente = _texto(it, "ambiente")
    r.ruc_agente = _texto(it, "ruc")
    r.razon_agente = _texto(it, "razonSocial")
    r.clave_acceso = _texto(it, "claveAcceso")
    r.estab, r.pto_emi, r.secuencial = _texto(it, "estab"), _texto(it, "ptoEmi"), _texto(it, "secuencial")
    r.fecha_emision = _fecha(_texto(info, "fechaEmision"))
    r.tipo_id_retenido = _texto(info, "tipoIdentificacionSujetoRetenido")
    r.id_retenido = _texto(info, "identificacionSujetoRetenido")
    r.razon_retenido = _texto(info, "razonSocialSujetoRetenido")
    r.periodo_fiscal = _texto(info, "periodoFiscal")

    def linea(e, cod_doc="", num_doc="", fecha_doc=None) -> LineaRetencion:
        return LineaRetencion(
            impuesto=_texto(e, "codigo"), codigo=_texto(e, "codigoRetencion"),
            base=_dec(_texto(e, "baseImponible")), porcentaje=_dec(_texto(e, "porcentajeRetener")),
            valor=_dec(_texto(e, "valorRetenido")),
            cod_doc_sustento=cod_doc or _texto(e, "codDocSustento"),
            num_doc_sustento=num_doc or _texto(e, "numDocSustento"),
            fecha_doc_sustento=fecha_doc or _fecha(_texto(e, "fechaEmisionDocSustento")))

    docs = _hijo(raiz, "docsSustento")
    if docs is not None:  # versión 2.0.0
        for d in docs:
            if not isinstance(d.tag, str) or _local(d.tag) != "docSustento":
                continue
            cod, num = _texto(d, "codDocSustento"), _texto(d, "numDocSustento")
            fecha = _fecha(_texto(d, "fechaEmisionDocSustento"))
            rets = _hijo(d, "retenciones")
            for e in rets if rets is not None else []:
                if isinstance(e.tag, str) and _local(e.tag) == "retencion":
                    r.lineas.append(linea(e, cod, num, fecha))
    impuestos = _hijo(raiz, "impuestos")
    if impuestos is not None:  # versión 1.0.0
        for e in impuestos:
            if isinstance(e.tag, str) and _local(e.tag) == "impuesto":
                r.lineas.append(linea(e))
    if not r.lineas:
        raise ErrorComprobante("El comprobante de retención no tiene valores retenidos")
    return r


# --- lectura PDF (RIDE) ---------------------------------------------------------------------
_DEC = r"\d[\d,]*\.\d{2,3}"


def desde_texto_ride(texto: str, clave: str, nombre: str) -> Retencion:
    """Interpreta el RIDE de un comprobante de retención (texto con disposición de página)."""
    from .comprobantes import _fecha, _num

    r = Retencion(archivo=nombre, origen="pdf", clave_acceso=clave, numero_autorizacion=clave)
    r.fecha_emision = _fecha(f"{clave[0:2]}/{clave[2:4]}/{clave[4:8]}")
    r.ruc_agente = clave[10:23]
    r.ambiente = clave[23]
    r.estab, r.pto_emi, r.secuencial = clave[24:27], clave[27:30], clave[30:39]
    if "PRUEBAS" in texto.upper() and "PRODUCCI" not in texto.upper():
        r.ambiente = "1"

    def buscar(patron: str) -> str:
        m = re.search(patron, texto, re.IGNORECASE | re.MULTILINE)
        return m.group(1).strip() if m else ""

    r.razon_retenido = buscar(r"Raz[oó]n\s+Social\s*/\s*Nombres\s+y\s+Apellidos:?[ \t]+(.+?)(?:\s{3,}|$)")
    r.id_retenido = buscar(r"Identificaci[oó]n:?[ \t]+([0-9A-Za-z-]{3,20})")
    r.tipo_id_retenido = "04" if len(r.id_retenido) == 13 else "05" if len(r.id_retenido) == 10 else "06"
    r.periodo_fiscal = buscar(r"(?:Ejercicio|Per[ií]odo)\s+Fiscal:?[ \t]+(\d{2}/\d{4})")
    r.lineas.extend(_filas_tabla_ride(texto))
    periodo = _periodo_en_tabla(texto)
    if not r.periodo_fiscal and periodo:
        r.periodo_fiscal = periodo
    for l in r.lineas:
        if l.impuesto == RENTA and not l.codigo:
            r.avisos_lectura.append("El PDF no trae el código de retención de renta: elíjalo en la columna «Cód. renta»")
            break
    for l in r.lineas:
        if abs(l.base * l.porcentaje / 100 - l.valor) > Decimal("0.02"):
            r.avisos_lectura.append(f"Línea leída del PDF sin cuadrar: {l.base} x {l.porcentaje}% ≠ {l.valor}")
    if not r.lineas:
        from .comprobantes import ErrorComprobante

        raise ErrorComprobante("No se encontraron valores retenidos en el PDF de la retención")
    return r


_FILA_RIDE = re.compile(
    rf"({_DEC})\s+(?:Impuesto\s+a\s+la\s+)?(RENTA|IVA|ISD)\b\s+(?:(\d{{1,4}}[A-Z]?\d?)\s+)?({_DEC}|\d{{1,3}})\s+({_DEC})",
    re.IGNORECASE)
_FECHAS = re.compile(r"\d{2}/\d{2}/\d{4}|\d{2}/\d{4}")


def _region_tabla(texto: str) -> list[str]:
    """Líneas de la tabla de retenciones del RIDE (entre el encabezado e 'Información Adicional')."""
    lineas = texto.splitlines()
    ini = next((i for i, l in enumerate(lineas)
                if re.search(r"Comprobante", l, re.I) and re.search(r"Impuesto|Base\s+Imponible|Porcentaje|Retenido", l, re.I)),
               -1)
    fin = next((i for i in range(ini + 1, len(lineas)) if re.search(r"Informaci[oó]n\s+Adicional", lineas[i], re.I)),
               len(lineas))
    return lineas[ini + 1:fin]


def _periodo_en_tabla(texto: str) -> str:
    for l in _region_tabla(texto):
        m = re.search(r"(?<![\d/])(\d{2}/\d{4})(?![\d/])", l)
        if m:
            return m.group(1)
    return ""


def _filas_tabla_ride(texto: str) -> list[LineaRetencion]:
    """Filas de la tabla del RIDE. Admite números de comprobante y textos partidos en varias líneas."""
    from .comprobantes import _fecha, _num

    region = _region_tabla(texto)
    filas: list[tuple[int, re.Match]] = []
    docs: list[tuple[int, str, str, dt.date | None]] = []  # (línea, número 15 dígitos, tipo, fecha)
    acumulado, inicio_doc = "", -1
    tipo_actual, fecha_actual = "01", None
    for i, l in enumerate(region):
        if re.search(r"LIQUIDACI", l, re.I):
            tipo_actual = "03"
        elif re.search(r"NOTA\s+DE\s+CR", l, re.I):
            tipo_actual = "04"
        elif re.search(r"NOTA\s+DE\s+D[EÉ]B", l, re.I):
            tipo_actual = "05"
        elif re.search(r"FACTURA", l, re.I):
            tipo_actual = "01"
        f = re.search(r"(\d{2}/\d{2}/\d{4})", l)
        if f:
            fecha_actual = _fecha(f.group(1))
        resto = l
        for m in _FILA_RIDE.finditer(l):
            filas.append((i, m))
        resto = _FILA_RIDE.sub(" ", resto)
        resto = re.sub(r"(\d{3})-(\d{3})-(\d{9})", r"\1\2\3", resto)
        resto = _FECHAS.sub(" ", resto)
        resto = re.sub(_DEC, " ", resto)
        for tok in re.findall(r"(?<![\d.,])\d+(?![\d.,])", resto):
            if len(acumulado) + len(tok) > 15:
                acumulado, inicio_doc = "", -1
            if not acumulado:
                inicio_doc = i
            acumulado += tok
            if len(acumulado) == 15:
                docs.append((inicio_doc, acumulado, tipo_actual, fecha_actual))
                acumulado, inicio_doc = "", -1
    salida = []
    for i, m in filas:
        doc = min(docs, key=lambda d: abs(d[0] - i)) if docs else (i, "", "01", None)
        impuesto = {"RENTA": RENTA, "IVA": IVA, "ISD": ISD}[m.group(2).upper()]
        porcentaje = _num(m.group(4))
        codigo = m.group(3) or ""
        if impuesto == IVA and not codigo:
            codigo = CODIGO_IVA_POR_PORCENTAJE.get(porcentaje, "")
        salida.append(LineaRetencion(impuesto, codigo, _num(m.group(1)), porcentaje, _num(m.group(5)),
                                     doc[2], doc[1], doc[3]))
    return salida


# --- códigos de renta recordados por proveedor --------------------------------------------------
def _ruta_codigos():
    from . import rutas

    return rutas.carpeta_datos() / "codigos_renta.json"


def _clave_pct(porcentaje: Decimal) -> str:
    return f"{porcentaje.normalize():f}"


def codigos_recordados() -> dict[str, dict[str, str]]:
    import json

    try:
        return json.loads(_ruta_codigos().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def recordar_codigos(ret: "Retencion") -> None:
    """Guarda el código de renta usado con este proveedor para cada porcentaje."""
    import json

    datos = codigos_recordados()
    cambios = False
    for l in ret.lineas:
        if l.impuesto == RENTA and l.codigo:
            por_ruc = datos.setdefault(ret.id_retenido, {})
            if por_ruc.get(_clave_pct(l.porcentaje)) != l.codigo:
                por_ruc[_clave_pct(l.porcentaje)] = l.codigo
                cambios = True
    if cambios:
        tmp = _ruta_codigos().with_suffix(".tmp")
        tmp.write_text(json.dumps(datos, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(_ruta_codigos())


def _codigo_sugerido(doc: Documento, proveedor: str, porcentaje: Decimal) -> str:
    compras = doc.raiz.hijo("compras")
    for c in compras.lista("detalleCompras") if compras is not None else []:
        if c.texto("idProv") != proveedor or c.hijo("air") is None:
            continue
        for a in c.hijo("air").lista("detalleAir"):
            try:
                if a.texto("codRetAir") and Decimal(a.texto("porcentajeAir")) == porcentaje:
                    return a.texto("codRetAir")
            except ArithmeticError:
                continue
    return codigos_recordados().get(proveedor, {}).get(_clave_pct(porcentaje), "")


def lineas_sin_codigo(ret: "Retencion") -> list[LineaRetencion]:
    return [l for l in ret.lineas if l.impuesto == RENTA and getattr(l, "codigo_leido", l.codigo) == ""]


# --- análisis -------------------------------------------------------------------------------
from .comprobantes import AVISO, OK, OMITIR  # noqa: E402


@dataclass
class PropuestaRetencion:
    retencion: Retencion
    destino: str  # ventas | compras
    estado: str
    notas: list[str]
    seleccionado: bool
    ya_registrado: bool = False
    objetivo: str = ""  # descripción de dónde se registrará


def _mm_aaaa(doc: Documento) -> str:
    return f"{doc.mes:02d}/{doc.anio}" if doc.mes and doc.anio else ""


def analizar(doc: Documento, retenciones: list[Retencion], propuestas_comprobantes=(),
             ya_importadas: set[str] | frozenset = frozenset()) -> list[PropuestaRetencion]:
    ruc = doc.raiz.texto("IdInformante")
    salida = []
    vistos: set[str] = set()
    for ret in retenciones:
        notas: list[str] = []
        estado = OK
        sel = True
        ya = False

        def omitir(t: str) -> None:
            nonlocal estado
            estado = OMITIR
            notas.append(t)

        def aviso(t: str) -> None:
            nonlocal estado
            if estado == OK:
                estado = AVISO
            notas.append(t)

        if ret.id_retenido == ruc:
            destino = "ventas"
        elif ret.ruc_agente == ruc:
            destino = "compras"
        else:
            destino = "ventas"
            omitir(f"La retención no es del informante: la emitió {ret.ruc_agente} a {ret.id_retenido}")
        if ret.ambiente == "1":
            omitir("Comprobante del ambiente de PRUEBAS")
        if ret.estado and ret.estado != "AUTORIZADO":
            omitir(f"Estado del comprobante: {ret.estado}")
        clave = ret.clave_acceso or f"{ret.ruc_agente}-{ret.numero}"
        if clave in vistos:
            omitir("Archivo repetido en esta importación")
        vistos.add(clave)
        for t in ret.avisos_lectura:
            if "código de retención de renta" in t:
                continue  # en ventas no se usa; en compras se trata más abajo
            aviso(t)
        if any(l.impuesto == ISD for l in ret.lineas):
            aviso("Incluye retención de ISD, que no se registra en el ATS")
        objetivo = ""
        if estado != OMITIR and destino == "ventas":
            periodo = _mm_aaaa(doc)
            if ret.periodo_fiscal and periodo and ret.periodo_fiscal != periodo:
                omitir(f"La retención corresponde al período {ret.periodo_fiscal} y el anexo es de {periodo}")
            elif clave in ya_importadas and _venta_con_retencion(doc, ret.ruc_agente):
                ya, sel = True, False
                aviso("Esta retención ya se importó antes en este anexo")
            else:
                tipos = {TIPO_VENTA_POR_SUSTENTO.get(l.cod_doc_sustento, "18") for l in ret.lineas}
                if not _hay_venta(doc, ret.ruc_agente, tipos, propuestas_comprobantes):
                    omitir(f"No hay ventas del cliente {ret.ruc_agente} en el anexo: importe primero su factura")
            objetivo = f"Venta a {ret.ruc_agente} {ret.razon_agente}".strip()
        elif estado != OMITIR:
            sin_codigo = lineas_sin_codigo(ret)
            for l in sin_codigo:
                if not l.codigo:
                    l.codigo = _codigo_sugerido(doc, ret.id_retenido, l.porcentaje)
            if sin_codigo:
                if all(l.codigo for l in sin_codigo):
                    aviso("Código de renta tomado de compras anteriores de este proveedor; verifíquelo en «Cód. renta»")
                else:
                    aviso("El comprobante no trae el código de retención de renta: elíjalo en la columna «Cód. renta»")
            faltan, registradas = [], 0
            for cod, num in ret.documentos():
                compra = _buscar_compra(doc, ret.id_retenido, cod, num)
                en_lote = compra is None and _compra_en_lote(ret.id_retenido, cod, num, propuestas_comprobantes)
                if compra is None and not en_lote:
                    faltan.append(_formato_num(num))
                elif compra is not None and _ya_tiene(compra, ret):
                    registradas += 1
            if faltan:
                omitir(f"No se encontró en el anexo la compra {', '.join(faltan)} del proveedor {ret.id_retenido}: "
                       "importe primero la factura")
            elif registradas == len(ret.documentos()):
                ya, sel = True, False
                omitir("Esta retención ya está registrada en la compra")
            objetivo = "Compra " + ", ".join(_formato_num(n) for _, n in ret.documentos())
        salida.append(PropuestaRetencion(ret, destino, estado, notas, estado != OMITIR and sel, ya, objetivo))
    return salida


def _formato_num(num: str) -> str:
    n = re.sub(r"\D", "", num)
    return f"{n[:3]}-{n[3:6]}-{n[6:]}" if len(n) >= 7 else num


def _venta_con_retencion(doc: Documento, cliente: str) -> bool:
    from .comprobantes import _dec

    ventas = doc.raiz.hijo("ventas")
    return any(v.texto("idCliente") == cliente and (_dec(v.texto("valorRetIva")) or _dec(v.texto("valorRetRenta")))
               for v in (ventas.lista("detalleVentas") if ventas is not None else []))


def _hay_venta(doc: Documento, cliente: str, tipos: set[str], propuestas) -> bool:
    ventas = doc.raiz.hijo("ventas")
    for v in ventas.lista("detalleVentas") if ventas is not None else []:
        if v.texto("idCliente") == cliente and v.texto("tipoComprobante") in tipos:
            return True
    from .comprobantes import TIPO_VENTA

    return any(p.destino == "ventas" and p.estado != OMITIR and p.comprobante.id_contraparte == cliente
               and TIPO_VENTA.get(p.comprobante.tipo) in tipos for p in propuestas)


def _buscar_compra(doc: Documento, proveedor: str, cod: str, num: str) -> Nodo | None:
    n = re.sub(r"\D", "", num)
    if len(n) < 7:
        return None
    estab, pto, sec = n[:3], n[3:6], n[6:]
    compras = doc.raiz.hijo("compras")
    for c in compras.lista("detalleCompras") if compras is not None else []:
        if (c.texto("idProv") == proveedor and (not cod or c.texto("tipoComprobante") == cod)
                and c.texto("establecimiento") == estab and c.texto("puntoEmision") == pto
                and c.texto("secuencial").lstrip("0") == sec.lstrip("0")):
            return c
    return None


def _compra_en_lote(proveedor: str, cod: str, num: str, propuestas) -> bool:
    n = re.sub(r"\D", "", num)
    for p in propuestas:
        c = p.comprobante
        if (p.destino == "compras" and p.estado != OMITIR and c.ruc_proveedor == proveedor
                and (not cod or c.tipo == cod) and f"{c.estab}{c.pto_emi}" == n[:6]
                and c.secuencial.lstrip("0") == n[6:].lstrip("0")):
            return True
    return False


def _ya_tiene(compra: Nodo, ret: Retencion) -> bool:
    for i in ("1", "2"):
        if (compra.texto(f"estabRetencion{i}") == ret.estab and compra.texto(f"ptoEmiRetencion{i}") == ret.pto_emi
                and compra.texto(f"secRetencion{i}").lstrip("0") == ret.secuencial.lstrip("0")):
            return True
    return False


# --- aplicación al anexo -------------------------------------------------------------------------
@dataclass
class ResultadoRetenciones:
    ventas: list[Nodo] = field(default_factory=list)
    compras: list[Nodo] = field(default_factory=list)
    claves_ventas: list[str] = field(default_factory=list)
    no_aplicadas: list[str] = field(default_factory=list)


def _sumar(nodo: Nodo, campo: str, valor: Decimal) -> None:
    from .comprobantes import _dec, _monto

    nodo.poner(campo, _monto(_dec(nodo.texto(campo)) + valor))


def aplicar(doc: Documento, propuestas: list[PropuestaRetencion]) -> ResultadoRetenciones:
    res = ResultadoRetenciones()
    for p in propuestas:
        if not p.seleccionado:
            continue
        ret = p.retencion
        if p.destino == "ventas":
            _aplicar_venta(doc, ret, res)
        else:
            _aplicar_compra(doc, ret, res)
    return res


def _aplicar_venta(doc: Documento, ret: Retencion, res: ResultadoRetenciones) -> None:
    ventas = doc.raiz.hijo("ventas")
    registros = ventas.lista("detalleVentas") if ventas is not None else []
    aplicada = False
    for l in ret.lineas:
        if l.impuesto not in (IVA, RENTA):
            continue
        tipo = TIPO_VENTA_POR_SUSTENTO.get(l.cod_doc_sustento, "18")
        candidatos = [v for v in registros if v.texto("idCliente") == ret.ruc_agente and v.texto("tipoComprobante") == tipo]
        if not candidatos:
            res.no_aplicadas.append(f"{ret.numero}: no hay ventas del cliente {ret.ruc_agente}")
            continue
        # se prefiere el registro con el tipo de emisión de las facturas importadas
        from .comprobantes import EMISION_VENTAS

        v = next((c for c in candidatos if c.texto("tipoEmision") == EMISION_VENTAS), candidatos[0])
        _sumar(v, "valorRetIva" if l.impuesto == IVA else "valorRetRenta", l.valor)
        if v not in res.ventas:
            res.ventas.append(v)
        aplicada = True
    if aplicada:
        res.claves_ventas.append(ret.clave_acceso or f"{ret.ruc_agente}-{ret.numero}")


def _aplicar_compra(doc: Documento, ret: Retencion, res: ResultadoRetenciones) -> None:
    for cod, num in ret.documentos():
        compra = _buscar_compra(doc, ret.id_retenido, cod, num)
        if compra is None:
            res.no_aplicadas.append(f"{ret.numero}: no se encontró la compra {_formato_num(num)}")
            continue
        if _ya_tiene(compra, ret):
            continue
        lineas = [l for l in ret.lineas if (l.cod_doc_sustento, l.num_doc_sustento) == (cod, num)]
        for l in lineas:
            if l.impuesto == IVA:
                campo = CAMPO_IVA_POR_PORCENTAJE.get(l.porcentaje)
                if campo is None:
                    res.no_aplicadas.append(f"{ret.numero}: porcentaje de retención de IVA no previsto ({l.porcentaje}%)")
                    continue
                _sumar(compra, campo, l.valor)
            elif l.impuesto == RENTA:
                _agregar_air(doc, compra, l)
        _poner_datos_retencion(compra, ret)
        res.compras.append(compra)


def _agregar_air(doc: Documento, compra: Nodo, l: LineaRetencion) -> None:
    from .comprobantes import _monto

    air = compra.hijo("air")
    if air is None:
        air = compra.agregar("air")
        for h in list(air.hijos):
            air.eliminar(h)
    detalle = crear_vacio(doc.esquema.raiz.buscar("detalleAir"))
    detalle.poner("codRetAir", l.codigo)
    detalle.poner("baseImpAir", _monto(l.base))
    detalle.poner("porcentajeAir", _monto(l.porcentaje))
    detalle.poner("valRetAir", _monto(l.valor))
    air.agregar("detalleAir", detalle)


def _poner_datos_retencion(compra: Nodo, ret: Retencion) -> None:
    i = "1" if not compra.texto("secRetencion1") else "2"
    compra.poner(f"estabRetencion{i}", ret.estab)
    compra.poner(f"ptoEmiRetencion{i}", ret.pto_emi)
    compra.poner(f"secRetencion{i}", ret.secuencial)
    compra.poner(f"autRetencion{i}", ret.autorizacion)
    if ret.fecha_emision:
        compra.poner(f"fechaEmiRet{i}", f"{ret.fecha_emision:%d/%m/%Y}")
