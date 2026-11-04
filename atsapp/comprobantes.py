"""Lectura de comprobantes electrónicos del SRI y conversión a registros de compras del ATS.

Acepta los XML tal como se descargan del portal SRI en línea (comprobantes
recibidos), que vienen dentro de un sobre <autorizacion> con el comprobante en un
CDATA, y también el XML firmado "suelto" que envían los proveedores por correo.
Se admiten: factura (01), liquidación de compra (03), nota de crédito (04) y nota
de débito (05). También se pueden pasar archivos ZIP con varios XML.

Los comprobantes emitidos POR el informante (sus ventas) también se pueden leer
desde el PDF (RIDE), porque el portal del SRI no permite descargar su XML: la clave
de acceso de 49 dígitos aporta tipo, fecha, RUC emisor, serie y secuencial, y del
texto del PDF se toman el cliente, los subtotales, el IVA y la forma de pago.
"""

from __future__ import annotations

import datetime as dt
import io
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path

from lxml import etree

from .catalogos import rango_periodo
from .documento import Documento, Nodo, crear_vacio

LIMITE_BYTES = 20 * 1024 * 1024

# Códigos de porcentaje de IVA de la ficha técnica de comprobantes electrónicos
IVA_TARIFA_CERO = {"0"}
IVA_NO_OBJETO = {"6"}
IVA_EXENTO = {"7"}
IVA_GRAVADO = {"2", "3", "4", "5", "8", "10"}
COD_IVA, COD_ICE = "2", "3"

TIPOS = {
    "factura": ("01", "Factura"),
    "liquidacionCompra": ("03", "Liquidación de compra"),
    "notaCredito": ("04", "Nota de crédito"),
    "notaDebito": ("05", "Nota de débito"),
}
NO_ADMITIDOS = {
    "guiaRemision": "Es una guía de remisión (no se registra en el ATS)",
}
# tipo de identificación del comprador/proveedor (comprobantes electrónicos) -> ATS compras
ID_A_ATS = {"04": "01", "05": "02", "06": "03", "08": "03"}

_PARSER = etree.XMLParser(resolve_entities=False, no_network=True, remove_comments=True, huge_tree=False,
                          remove_blank_text=True)


class ErrorComprobante(Exception):
    pass


@dataclass
class Comprobante:
    archivo: str
    elemento: str = ""
    tipo: str = ""  # código ATS: 01, 03, 04, 05
    tipo_nombre: str = ""
    ambiente: str = ""  # 1 pruebas, 2 producción
    estado: str = ""  # AUTORIZADO, NO AUTORIZADO... (vacío si no viene en el archivo)
    ruc_emisor: str = ""
    razon_emisor: str = ""
    # contraparte: comprador (facturas, NC, ND) o proveedor (liquidaciones)
    tipo_id_contraparte: str = ""
    id_contraparte: str = ""
    razon_contraparte: str = ""
    estab: str = ""
    pto_emi: str = ""
    secuencial: str = ""
    fecha_emision: dt.date | None = None
    clave_acceso: str = ""
    numero_autorizacion: str = ""
    base_cero: Decimal = Decimal(0)
    base_gravada: Decimal = Decimal(0)
    base_no_objeto: Decimal = Decimal(0)
    base_exenta: Decimal = Decimal(0)
    iva: Decimal = Decimal(0)
    ice: Decimal = Decimal(0)
    total: Decimal = Decimal(0)
    formas_pago: list[str] = field(default_factory=list)
    # comprobante modificado (notas de crédito y débito)
    mod_tipo: str = ""
    mod_estab: str = ""
    mod_pto: str = ""
    mod_sec: str = ""
    origen: str = "xml"  # xml | pdf
    cuadra: bool = True  # en PDF: la suma de subtotales e impuestos coincide con el total
    irbpnr: Decimal = Decimal(0)
    propina: Decimal = Decimal(0)

    @property
    def numero(self) -> str:
        return f"{self.estab}-{self.pto_emi}-{self.secuencial}"

    @property
    def autorizacion(self) -> str:
        return self.numero_autorizacion or self.clave_acceso

    @property
    def es_liquidacion(self) -> bool:
        return self.tipo == "03"

    @property
    def ruc_proveedor(self) -> str:
        return self.id_contraparte if self.es_liquidacion else self.ruc_emisor

    @property
    def razon_proveedor(self) -> str:
        return self.razon_contraparte if self.es_liquidacion else self.razon_emisor

    @property
    def tp_id_proveedor(self) -> str:
        if self.es_liquidacion:
            return ID_A_ATS.get(self.tipo_id_contraparte, "")
        return "01"

    @property
    def tp_id_cliente(self) -> str:
        """Tipo de identificación del cliente para el módulo de ventas del ATS."""
        if self.id_contraparte == "9999999999999":
            return "07"
        return {"04": "04", "05": "05", "06": "06", "07": "07", "08": "06"}.get(self.tipo_id_contraparte, "")

    @property
    def base_total(self) -> Decimal:
        return self.base_cero + self.base_gravada + self.base_no_objeto + self.base_exenta

    @property
    def suma_compra(self) -> Decimal:
        return self.base_cero + self.base_gravada + self.base_no_objeto + self.base_exenta + self.iva + self.ice


@dataclass
class ArchivoNoLeido:
    archivo: str
    motivo: str


# --- lectura --------------------------------------------------------------------------
def leer_rutas(rutas: list[str | Path]) -> list[Comprobante | ArchivoNoLeido]:
    """Lee archivos XML, ZIP o carpetas (se recorren los .xml y .zip que contengan)."""
    resultado: list[Comprobante | ArchivoNoLeido] = []
    for ruta in rutas:
        ruta = Path(ruta)
        if ruta.is_dir():
            hijos = sorted(p for p in ruta.rglob("*") if p.suffix.lower() in (".xml", ".zip", ".pdf"))
            resultado += leer_rutas(hijos)
            continue
        try:
            if ruta.stat().st_size > LIMITE_BYTES:
                raise ErrorComprobante("El archivo es demasiado grande")
            if ruta.suffix.lower() == ".zip":
                resultado += _leer_zip(ruta)
            elif ruta.suffix.lower() == ".pdf":
                resultado.append(leer_pdf(ruta.read_bytes(), ruta.name))
            else:
                resultado.append(leer_bytes(ruta.read_bytes(), ruta.name))
        except (ErrorComprobante, OSError, zipfile.BadZipFile) as e:
            resultado.append(ArchivoNoLeido(ruta.name, str(e)))
    return resultado


def _leer_zip(ruta: Path) -> list[Comprobante | ArchivoNoLeido]:
    salida: list[Comprobante | ArchivoNoLeido] = []
    with zipfile.ZipFile(ruta) as z:
        for info in z.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".xml"):
                continue
            nombre = f"{ruta.name}/{info.filename}"
            if info.file_size > LIMITE_BYTES:
                salida.append(ArchivoNoLeido(nombre, "El archivo es demasiado grande"))
                continue
            try:
                salida.append(leer_bytes(z.read(info), nombre))
            except ErrorComprobante as e:
                salida.append(ArchivoNoLeido(nombre, str(e)))
    return salida


def leer_bytes(datos: bytes, nombre: str = ""):
    """Devuelve un Comprobante (factura, NC, ND, liquidación) o una Retencion."""
    try:
        raiz = etree.parse(io.BytesIO(datos), _PARSER).getroot()
    except etree.XMLSyntaxError as e:
        raise ErrorComprobante(f"No es un XML válido: {e}") from None
    comp = Comprobante(archivo=nombre)
    raiz = _desenvolver(raiz, comp)
    elemento = _local(raiz.tag)
    if elemento == "comprobanteRetencion":
        from .retenciones import desde_xml

        return desde_xml(raiz, nombre, comp.estado, comp.numero_autorizacion)
    if elemento in NO_ADMITIDOS:
        raise ErrorComprobante(NO_ADMITIDOS[elemento])
    if elemento == "iva":
        raise ErrorComprobante("Es un anexo ATS, no un comprobante (use Archivo → Abrir)")
    if elemento not in TIPOS:
        raise ErrorComprobante(f"No es un comprobante electrónico reconocido (<{elemento}>)")
    comp.elemento = elemento
    comp.tipo, comp.tipo_nombre = TIPOS[elemento]
    _info_tributaria(raiz, comp)
    {"factura": _factura, "liquidacionCompra": _liquidacion,
     "notaCredito": _nota_credito, "notaDebito": _nota_debito}[elemento](raiz, comp)
    return comp


def _desenvolver(raiz, comp: Comprobante):
    """Si el XML es el sobre de autorización del SRI, devuelve el comprobante interno."""
    if _local(raiz.tag) not in ("autorizacion", "RespuestaAutorizacionComprobante", "respuestaComprobante"):
        return raiz
    aut = raiz if _local(raiz.tag) == "autorizacion" else _buscar(raiz, "autorizacion")
    if aut is None:
        raise ErrorComprobante("El archivo de autorización no contiene ningún comprobante")
    comp.estado = _texto(aut, "estado").upper()
    comp.numero_autorizacion = _texto(aut, "numeroAutorizacion")
    nodo = _hijo(aut, "comprobante")
    if nodo is None:
        raise ErrorComprobante("El archivo de autorización no contiene el comprobante")
    internos = [h for h in nodo if isinstance(h.tag, str)]
    if internos:
        return internos[0]
    texto = (nodo.text or "").strip()
    if not texto:
        raise ErrorComprobante("El comprobante está vacío")
    try:
        return etree.parse(io.BytesIO(texto.encode("utf-8")), _PARSER).getroot()
    except etree.XMLSyntaxError as e:
        raise ErrorComprobante(f"El comprobante interno no es un XML válido: {e}") from None


def _info_tributaria(raiz, comp: Comprobante) -> None:
    it = _hijo(raiz, "infoTributaria")
    if it is None:
        raise ErrorComprobante("Falta la sección infoTributaria")
    comp.ambiente = _texto(it, "ambiente")
    comp.razon_emisor = _texto(it, "razonSocial")
    comp.ruc_emisor = _texto(it, "ruc")
    comp.clave_acceso = _texto(it, "claveAcceso")
    comp.estab = _texto(it, "estab")
    comp.pto_emi = _texto(it, "ptoEmi")
    comp.secuencial = _texto(it, "secuencial")


def _comunes(info, comp: Comprobante, prefijo: str) -> None:
    comp.fecha_emision = _fecha(_texto(info, "fechaEmision"))
    comp.tipo_id_contraparte = _texto(info, f"tipoIdentificacion{prefijo}")
    comp.id_contraparte = _texto(info, f"identificacion{prefijo}")
    comp.razon_contraparte = _texto(info, f"razonSocial{prefijo}")


def _factura(raiz, comp: Comprobante) -> None:
    info = _requerido(raiz, "infoFactura")
    _comunes(info, comp, "Comprador")
    _impuestos(_hijo(info, "totalConImpuestos"), "totalImpuesto", comp)
    comp.total = _dec(_texto(info, "importeTotal"))
    _pagos(info, comp)


def _liquidacion(raiz, comp: Comprobante) -> None:
    info = _requerido(raiz, "infoLiquidacionCompra")
    _comunes(info, comp, "Proveedor")
    _impuestos(_hijo(info, "totalConImpuestos"), "totalImpuesto", comp)
    comp.total = _dec(_texto(info, "importeTotal"))
    _pagos(info, comp)


def _nota_credito(raiz, comp: Comprobante) -> None:
    info = _requerido(raiz, "infoNotaCredito")
    _comunes(info, comp, "Comprador")
    _impuestos(_hijo(info, "totalConImpuestos"), "totalImpuesto", comp)
    comp.total = _dec(_texto(info, "valorModificacion"))
    _doc_modificado(info, comp)


def _nota_debito(raiz, comp: Comprobante) -> None:
    info = _requerido(raiz, "infoNotaDebito")
    _comunes(info, comp, "Comprador")
    _impuestos(_hijo(info, "impuestos"), "impuesto", comp)
    comp.total = _dec(_texto(info, "valorTotal"))
    _doc_modificado(info, comp)
    _pagos(info, comp)


def _doc_modificado(info, comp: Comprobante) -> None:
    comp.mod_tipo = _texto(info, "codDocModificado")
    partes = _texto(info, "numDocModificado").split("-")
    if len(partes) == 3:
        comp.mod_estab, comp.mod_pto, comp.mod_sec = partes


def _impuestos(contenedor, etiqueta: str, comp: Comprobante) -> None:
    if contenedor is None:
        return
    for imp in contenedor:
        if not isinstance(imp.tag, str) or _local(imp.tag) != etiqueta:
            continue
        codigo, pct = _texto(imp, "codigo"), _texto(imp, "codigoPorcentaje")
        base, valor = _dec(_texto(imp, "baseImponible")), _dec(_texto(imp, "valor"))
        if codigo == COD_IVA:
            if pct in IVA_TARIFA_CERO:
                comp.base_cero += base
            elif pct in IVA_NO_OBJETO:
                comp.base_no_objeto += base
            elif pct in IVA_EXENTO:
                comp.base_exenta += base
            else:
                comp.base_gravada += base
                comp.iva += valor
        elif codigo == COD_ICE:
            comp.ice += valor


def _pagos(info, comp: Comprobante) -> None:
    pagos = _hijo(info, "pagos")
    if pagos is None:
        return
    for p in pagos:
        if isinstance(p.tag, str) and _local(p.tag) == "pago":
            codigo = _texto(p, "formaPago")
            if codigo and codigo not in comp.formas_pago:
                comp.formas_pago.append(codigo)


# --- utilidades XML ---------------------------------------------------------------------
def _local(tag) -> str:
    return etree.QName(tag).localname if isinstance(tag, str) else ""


def _hijo(e, nombre: str):
    for h in e:
        if isinstance(h.tag, str) and _local(h.tag) == nombre:
            return h
    return None


def _buscar(e, nombre: str):
    for h in e.iter():
        if isinstance(h.tag, str) and _local(h.tag) == nombre:
            return h
    return None


def _requerido(e, nombre: str):
    h = _hijo(e, nombre)
    if h is None:
        raise ErrorComprobante(f"Falta la sección {nombre}")
    return h


def _texto(e, nombre: str) -> str:
    h = _hijo(e, nombre)
    return (h.text or "").strip() if h is not None else ""


def _dec(t: str) -> Decimal:
    try:
        return Decimal(t) if t else Decimal(0)
    except InvalidOperation:
        return Decimal(0)


def _fecha(t: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(t, "%d/%m/%Y").date()
    except ValueError:
        return None


# --- PDF (RIDE) -------------------------------------------------------------------------------
import re as _re

_NUM = r"(-?[\d,]*\d\.\d{2})"
TIPOS_POR_CODIGO = {v[0]: (k, v[1]) for k, v in TIPOS.items()}


def _num(t: str) -> Decimal:
    return _dec(t.replace(",", ""))


def leer_pdf(datos: bytes, nombre: str = "") -> Comprobante:
    """Lee la representación impresa (RIDE) de un comprobante electrónico."""
    try:
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError
    except ImportError:  # pragma: no cover
        raise ErrorComprobante("Falta la librería pypdf para leer PDF (pip install pypdf)") from None
    try:
        lector = PdfReader(io.BytesIO(datos))
        if lector.is_encrypted:
            raise ErrorComprobante("El PDF está protegido con contraseña")
        texto = "\n".join(p.extract_text(extraction_mode="layout") or "" for p in lector.pages[:10])
    except (PdfReadError, ValueError, KeyError, OSError) as e:
        raise ErrorComprobante(f"No se pudo leer el PDF: {e}") from None
    return comprobante_desde_texto_ride(texto, nombre)


def comprobante_desde_texto_ride(texto: str, nombre: str = "") -> Comprobante:
    """Interpreta el texto (con disposición de página) de un RIDE."""
    from .identificacion import clave_acceso_valida

    claves = [c for c in _re.findall(r"(?<!\d)\d{49}(?!\d)", texto) if clave_acceso_valida(c)]
    if not claves:
        raise ErrorComprobante("El PDF no tiene una clave de acceso de 49 dígitos válida (¿es un RIDE del SRI?)")
    clave = claves[0]
    cod = clave[8:10]
    if cod == "07":
        from .retenciones import desde_texto_ride

        return desde_texto_ride(texto, clave, nombre)
    if cod not in TIPOS_POR_CODIGO:
        raise ErrorComprobante(f"Tipo de comprobante {cod} no admitido")
    comp = Comprobante(archivo=nombre, origen="pdf")
    comp.elemento, comp.tipo_nombre = TIPOS_POR_CODIGO[cod]
    comp.tipo = cod
    comp.clave_acceso = comp.numero_autorizacion = clave
    comp.fecha_emision = _fecha(f"{clave[0:2]}/{clave[2:4]}/{clave[4:8]}")
    comp.ruc_emisor = clave[10:23]
    comp.ambiente = clave[23]
    comp.estab, comp.pto_emi, comp.secuencial = clave[24:27], clave[27:30], clave[30:39]
    if "PRUEBAS" in texto.upper() and "PRODUCCI" not in texto.upper():
        comp.ambiente = "1"

    def buscar(patron: str) -> str:
        m = _re.search(patron, texto, _re.IGNORECASE | _re.MULTILINE)
        return m.group(1).strip() if m else ""

    comp.razon_contraparte = buscar(r"Raz[oó]n\s+Social\s*/\s*Nombres\s+y\s+Apellidos:?[ \t]+(.+?)(?:\s{3,}|$)")
    if comp.elemento == "liquidacionCompra":
        comp.razon_contraparte = comp.razon_contraparte or buscar(r"Proveedor:?[ \t]+(.+?)(?:\s{3,}|$)")
    ident = buscar(r"Identificaci[oó]n:?[ \t]+([0-9A-Za-z-]{3,20})")
    comp.id_contraparte = ident
    if ident == "9999999999999":
        comp.tipo_id_contraparte = "07"
    elif ident.isdigit() and len(ident) == 13:
        comp.tipo_id_contraparte = "04"
    elif ident.isdigit() and len(ident) == 10:
        comp.tipo_id_contraparte = "05"
    elif ident:
        comp.tipo_id_contraparte = "06"
    for pct, valor in _re.findall(r"SUBTOTAL\s+(\d+(?:[.,]\d+)?)\s*%\s+" + _NUM, texto, _re.IGNORECASE):
        if _num(pct) == 0:
            comp.base_cero += _num(valor)
        else:
            comp.base_gravada += _num(valor)
    comp.base_no_objeto = _num(buscar(r"SUBTOTAL\s+NO\s+OBJETO\s+DE\s+IVA\s+" + _NUM))
    comp.base_exenta = _num(buscar(r"SUBTOTAL\s+EXENTO\s+DE\s+IVA\s+" + _NUM))
    comp.ice = _num(buscar(r"(?<![A-Z])ICE\s+" + _NUM))
    comp.irbpnr = _num(buscar(r"IRBPNR\s+" + _NUM))
    comp.propina = _num(buscar(r"PROPINA\s+" + _NUM))
    for valor in _re.findall(r"(?<![A-Z])IVA\s+\d+(?:[.,]\d+)?\s*%\s+" + _NUM, texto, _re.IGNORECASE):
        comp.iva += _num(valor)
    comp.total = _num(buscar(r"VALOR\s+TOTAL(?!\s+SIN)\s+" + _NUM) or buscar(r"VALOR\s+MODIFICACI[OÓ]N\s+" + _NUM))
    for codigo in _re.findall(r"^\s*(\d{2})\s*-\s*[A-ZÁÉÍÓÚÑ]", texto, _re.MULTILINE):
        if codigo not in comp.formas_pago:
            comp.formas_pago.append(codigo)
    if comp.tipo in ("04", "05"):
        propio = comp.numero
        otros = [n for n in _re.findall(r"(\d{3}-\d{3}-\d{9})", texto) if n != propio]
        if otros:
            comp.mod_tipo = "01"
            comp.mod_estab, comp.mod_pto, comp.mod_sec = otros[0].split("-")
    suma = comp.base_total + comp.iva + comp.ice + comp.irbpnr + comp.propina
    comp.cuadra = bool(comp.total) and abs(suma - comp.total) <= Decimal("0.02")
    return comp


# --- análisis frente al anexo ---------------------------------------------------------------
OK, AVISO, OMITIR = "ok", "aviso", "omitir"


@dataclass
class Propuesta:
    comprobante: Comprobante
    estado: str  # ok | aviso | omitir
    notas: list[str]
    sustento: str
    parte_rel: str
    fecha_registro: dt.date | None
    seleccionado: bool
    ya_registrado: bool = False
    destino: str = "compras"  # compras | ventas


def _monto(d: Decimal) -> str:
    return f"{d.quantize(Decimal('0.01'))}"


def es_venta(comp: Comprobante, ruc_informante: str) -> bool:
    return bool(ruc_informante) and comp.ruc_emisor == ruc_informante and comp.tipo in ("01", "04", "05")


def analizar(doc: Documento, comprobantes: list[Comprobante], sustento_defecto: str = "01",
             umbral_forma_pago=None, ventas_importadas: set[str] | frozenset = frozenset()) -> list[Propuesta]:
    """Decide qué comprobantes se agregan, a qué módulo (compras o ventas) y con qué datos."""
    ruc = doc.raiz.texto("IdInformante")
    i_ventas = [i for i, c in enumerate(comprobantes) if es_venta(c, ruc)]
    i_compras = [i for i, c in enumerate(comprobantes) if not es_venta(c, ruc)]
    resultado: list[Propuesta | None] = [None] * len(comprobantes)
    for i, p in zip(i_compras, _analizar_compras(doc, [comprobantes[i] for i in i_compras], sustento_defecto,
                                                 umbral_forma_pago)):
        resultado[i] = p
    for i, p in zip(i_ventas, _analizar_ventas(doc, [comprobantes[i] for i in i_ventas], ventas_importadas)):
        resultado[i] = p
    return resultado


def _analizar_compras(doc: Documento, comprobantes: list[Comprobante], sustento_defecto: str,
                      umbral_forma_pago) -> list[Propuesta]:
    raiz = doc.raiz
    ruc_informante = raiz.texto("IdInformante")
    semestral = raiz.texto("regimenMicroempresa") == "SI"
    inicio, fin = rango_periodo(doc.anio, doc.mes, semestral)
    compras = raiz.hijo("compras").lista("detalleCompras") if raiz.hijo("compras") else []
    existentes = {_clave_compra(c) for c in compras}
    previo_por_ruc = {c.texto("idProv"): c for c in compras}
    vistos: set[tuple] = set()
    propuestas: list[Propuesta] = []
    for comp in comprobantes:
        notas: list[str] = []
        estado = OK
        ruc_prov = comp.ruc_proveedor
        anterior = previo_por_ruc.get(ruc_prov)
        sustento = anterior.texto("codSustento") if anterior is not None else sustento_defecto
        parte_rel = anterior.texto("parteRel") if anterior is not None and anterior.texto("parteRel") else "NO"

        def omitir(texto: str) -> None:
            nonlocal estado
            estado = OMITIR
            notas.append(texto)

        def aviso(texto: str) -> None:
            nonlocal estado
            if estado == OK:
                estado = AVISO
            notas.append(texto)

        if comp.ambiente == "1":
            omitir("Comprobante del ambiente de PRUEBAS (no tiene validez tributaria)")
        if comp.estado and comp.estado != "AUTORIZADO":
            omitir(f"Estado del comprobante: {comp.estado}")
        if comp.es_liquidacion:
            if ruc_informante and comp.ruc_emisor != ruc_informante:
                omitir(f"La liquidación de compra fue emitida por {comp.ruc_emisor}, no por el informante")
        elif ruc_informante and comp.id_contraparte != ruc_informante:
            omitir(f"Emitido a nombre de {comp.id_contraparte} {comp.razon_contraparte}".strip()
                   + " y no del informante")
        if comp.fecha_emision is None:
            omitir("No tiene una fecha de emisión válida")
        fecha_reg = comp.fecha_emision
        if comp.fecha_emision and inicio:
            if comp.fecha_emision > fin:
                omitir(f"Emitido el {comp.fecha_emision:%d/%m/%Y}, después del período del anexo")
            elif comp.fecha_emision < inicio:
                fecha_reg = inicio
                aviso(f"Emitido en un período anterior ({comp.fecha_emision:%d/%m/%Y}); "
                      f"se registra con fecha {inicio:%d/%m/%Y}")
        clave = (comp.tp_id_proveedor, ruc_prov, comp.tipo, comp.estab, comp.pto_emi, comp.secuencial)
        ya_registrado = clave in existentes
        if ya_registrado:
            omitir("Ya está registrado en las compras del anexo")
        elif clave in vistos:
            omitir("Archivo repetido en esta importación")
        vistos.add(clave)
        if not comp.tp_id_proveedor:
            aviso("No se reconoce el tipo de identificación del proveedor")
        if comp.tipo in ("04", "05"):
            if not comp.mod_sec:
                aviso("No se indica el comprobante que modifica")
            elif not _autorizacion_modificado(comp, compras, comprobantes):
                aviso("No se encontró la factura que modifica: complete su número de autorización al editar")
        umbral = _umbral(comp.fecha_emision) if umbral_forma_pago is None else umbral_forma_pago
        if comp.tipo in ("01", "03", "05") and comp.suma_compra > umbral and not comp.formas_pago:
            aviso(f"Supera USD {umbral} y el comprobante no trae forma de pago; agréguela al editar")
        if not comp.cuadra:
            aviso("Los valores leídos del PDF no suman el valor total; revíselos al editar")
        propuestas.append(Propuesta(comp, estado, notas, sustento, parte_rel, fecha_reg, estado != OMITIR,
                                    ya_registrado and len(notas) == 1))
    return propuestas


def _clave_venta(tp: str, ident: str, tipo: str, emision: str) -> tuple:
    return (tp, ident, tipo, emision)


TIPO_VENTA = {"01": "18", "04": "04", "05": "05"}  # factura -> 18 (documentos autorizados en ventas)
# Tipo de emisión con el que se registran las ventas importadas. DIMM solo suma al total de
# ventas los registros con emisión física (F); el usuario eligió registrarlas como F.
EMISION_VENTAS = "F"


def _analizar_ventas(doc: Documento, comprobantes: list[Comprobante], ya_importadas) -> list[Propuesta]:
    raiz = doc.raiz
    semestral = raiz.texto("regimenMicroempresa") == "SI"
    inicio, fin = rango_periodo(doc.anio, doc.mes, semestral)
    existentes = set()
    if raiz.hijo("ventas") is not None:
        for v in raiz.hijo("ventas").lista("detalleVentas"):
            existentes.add((v.texto("tpIdCliente"), v.texto("idCliente"), v.texto("tipoComprobante")))
    vistos: set[str] = set()
    propuestas = []
    for comp in comprobantes:
        notas: list[str] = []
        estado = OK
        seleccionar = True
        ya = False

        def omitir(texto: str) -> None:
            nonlocal estado
            estado = OMITIR
            notas.append(texto)

        def aviso(texto: str) -> None:
            nonlocal estado
            if estado == OK:
                estado = AVISO
            notas.append(texto)

        if comp.ambiente == "1":
            omitir("Comprobante del ambiente de PRUEBAS (no tiene validez tributaria)")
        if comp.estado and comp.estado != "AUTORIZADO":
            omitir(f"Estado del comprobante: {comp.estado}")
        if comp.fecha_emision is None:
            omitir("No tiene una fecha de emisión válida")
        elif inicio and not (inicio <= comp.fecha_emision <= fin):
            omitir(f"Venta emitida el {comp.fecha_emision:%d/%m/%Y}, fuera del período del anexo")
        clave = comp.clave_acceso or comp.numero
        # el registro de importadas solo cuenta si el anexo abierto tiene ventas de ese cliente
        cliente_en_anexo = (comp.tp_id_cliente, comp.id_contraparte, TIPO_VENTA.get(comp.tipo)) in existentes
        if clave in ya_importadas and cliente_en_anexo:
            ya = True
            seleccionar = False
            aviso("Esta venta ya se importó antes en este anexo")
        elif clave in vistos:
            omitir("Archivo repetido en esta importación")
        vistos.add(clave)
        if not comp.id_contraparte or not comp.tp_id_cliente:
            omitir("No se pudo leer la identificación del cliente")
        if estado != OMITIR:
            if not ya and (comp.tp_id_cliente, comp.id_contraparte, TIPO_VENTA[comp.tipo]) in existentes:
                seleccionar = False
                aviso("El anexo ya tiene ventas de este cliente; márquela solo si esta factura no está incluida")
            if not comp.cuadra:
                aviso("Los valores leídos del PDF no suman el valor total; revíselos")
            if comp.tipo != "04" and not comp.formas_pago:
                aviso("No trae forma de cobro; agréguela al editar la venta")
            if comp.base_exenta:
                aviso("Tiene base exenta de IVA; en ventas se suma a la base no objeto de IVA")
        propuestas.append(Propuesta(comp, estado, notas, "", "NO", comp.fecha_emision,
                                    estado != OMITIR and seleccionar, ya and estado != OMITIR, "ventas"))
    return propuestas


def _umbral(fecha: dt.date | None) -> Decimal:
    from .reglas import FECHA_CAMBIO_UMBRAL_PAGO

    if fecha is None or fecha >= FECHA_CAMBIO_UMBRAL_PAGO:
        return Decimal(500)
    return Decimal(1000)


def _clave_compra(c: Nodo) -> tuple:
    return tuple(c.texto(k) for k in ("tpIdProv", "idProv", "tipoComprobante", "establecimiento", "puntoEmision", "secuencial"))


def _autorizacion_modificado(comp: Comprobante, compras: list[Nodo], lote: list[Comprobante]) -> str:
    """Busca la autorización del comprobante que modifica la nota (en el anexo o en el mismo lote)."""
    if not comp.mod_sec:
        return ""
    for c in compras:
        if (c.texto("idProv") == comp.ruc_proveedor and c.texto("tipoComprobante") == comp.mod_tipo
                and c.texto("establecimiento") == comp.mod_estab and c.texto("puntoEmision") == comp.mod_pto
                and c.texto("secuencial").lstrip("0") == comp.mod_sec.lstrip("0")):
            return c.texto("autorizacion")
    for otro in lote:
        if (otro.ruc_proveedor == comp.ruc_proveedor and otro.tipo == comp.mod_tipo and otro.estab == comp.mod_estab
                and otro.pto_emi == comp.mod_pto and otro.secuencial.lstrip("0") == comp.mod_sec.lstrip("0")):
            return otro.autorizacion
    return ""


def crear_compra(doc: Documento, p: Propuesta, lote: list[Comprobante]) -> Nodo:
    """Construye un registro detalleCompras a partir de un comprobante."""
    comp = p.comprobante
    defn = doc.esquema.raiz.buscar("detalleCompras")
    n = crear_vacio(defn)
    cero = "0.00"
    valores = {
        "codSustento": p.sustento,
        "tpIdProv": comp.tp_id_proveedor,
        "idProv": comp.ruc_proveedor,
        "tipoComprobante": comp.tipo,
        "parteRel": p.parte_rel,
        "fechaRegistro": f"{p.fecha_registro:%d/%m/%Y}" if p.fecha_registro else "",
        "establecimiento": comp.estab,
        "puntoEmision": comp.pto_emi,
        "secuencial": comp.secuencial,
        "fechaEmision": f"{comp.fecha_emision:%d/%m/%Y}" if comp.fecha_emision else "",
        "autorizacion": comp.autorizacion,
        "baseNoGraIva": _monto(comp.base_no_objeto),
        "baseImponible": _monto(comp.base_cero),
        "baseImpGrav": _monto(comp.base_gravada),
        "baseImpExe": _monto(comp.base_exenta),
        "montoIce": _monto(comp.ice),
        "montoIva": _monto(comp.iva),
        "valRetBien10": cero, "valRetServ20": cero, "valorRetBienes": cero, "valRetServ50": cero,
        "valorRetServicios": cero, "valRetServ100": cero, "valorRetencionNc": cero, "totbasesImpReemb": cero,
    }
    if comp.tp_id_proveedor == "03":
        valores["tipoProv"] = "01"
        valores["denoProv"] = _solo_letras(comp.razon_proveedor)
    for campo, valor in valores.items():
        if defn.hijo(campo) is not None and valor != "":
            n.poner(campo, valor)
        elif defn.hijo(campo) is not None and n.hijo(campo) is not None:
            n.hijo(campo).valor = valor
    pe = n.hijo("pagoExterior") or (n.agregar("pagoExterior") if defn.hijo("pagoExterior") else None)
    if pe is not None:
        for campo, valor in (("pagoLocExt", "01"), ("paisEfecPago", "NA"), ("aplicConvDobTrib", "NA"),
                             ("pagExtSujRetNorLeg", "NA")):
            if pe.defn.hijo(campo) is not None:
                pe.poner(campo, valor)
    if comp.formas_pago and comp.suma_compra > _umbral(comp.fecha_emision) and defn.hijo("formasDePago") is not None:
        fp = n.hijo("formasDePago") or n.agregar("formasDePago")
        for h in list(fp.hijos):
            fp.eliminar(h)
        for codigo in comp.formas_pago:
            fp.agregar("formaPago").valor = codigo
    if comp.tipo in ("04", "05") and comp.mod_sec:
        compras = doc.raiz.hijo("compras").lista("detalleCompras") if doc.raiz.hijo("compras") else []
        for campo, valor in (("docModificado", comp.mod_tipo), ("estabModificado", comp.mod_estab),
                             ("ptoEmiModificado", comp.mod_pto), ("secModificado", comp.mod_sec),
                             ("autModificado", _autorizacion_modificado(comp, compras, lote))):
            if defn.hijo(campo) is not None:
                n.poner(campo, valor)
    return n


@dataclass
class ResultadoImportacion:
    compras: list[Nodo] = field(default_factory=list)
    ventas: list[Nodo] = field(default_factory=list)  # registros de ventas creados o actualizados
    claves_ventas: list[str] = field(default_factory=list)

    def __len__(self) -> int:  # compatibilidad: cantidad de compras agregadas
        return len(self.compras)

    def __getitem__(self, i):
        return self.compras[i]


def importar(doc: Documento, propuestas: list[Propuesta]) -> ResultadoImportacion:
    """Agrega al anexo las propuestas seleccionadas."""
    res = ResultadoImportacion()
    lote = [p.comprobante for p in propuestas]
    elegidas = [p for p in propuestas if p.seleccionado]
    if any(p.destino == "compras" for p in elegidas):
        compras = _contenedor(doc.raiz, "compras")
        for p in elegidas:
            if p.destino == "compras":
                nodo = crear_compra(doc, p, lote)
                compras.agregar("detalleCompras", nodo)
                res.compras.append(nodo)
    por_estab: dict[str, Decimal] = {}
    for p in elegidas:
        if p.destino != "ventas":
            continue
        nodo = _sumar_venta(doc, p.comprobante)
        if nodo not in res.ventas:
            res.ventas.append(nodo)
        res.claves_ventas.append(p.comprobante.clave_acceso or p.comprobante.numero)
        signo = -1 if p.comprobante.tipo == "04" else 1
        por_estab[p.comprobante.estab] = por_estab.get(p.comprobante.estab, Decimal(0)) + signo * p.comprobante.base_total
    if por_estab:
        _actualizar_establecimientos(doc, por_estab)
    return res


def _contenedor(raiz: Nodo, nombre: str) -> Nodo:
    """Devuelve la sección (compras, ventas...) creándola vacía si no existe."""
    nodo = raiz.hijo(nombre)
    if nodo is None:
        nodo = raiz.agregar(nombre)
        for h in list(nodo.hijos):  # sin registros vacíos de relleno
            nodo.eliminar(h)
    return nodo


def _sumar_venta(doc: Documento, comp: Comprobante) -> Nodo:
    """Suma el comprobante al registro del cliente (un registro por cliente, tipo y emisión)."""
    raiz = doc.raiz
    ventas = _contenedor(raiz, "ventas")
    tipo = TIPO_VENTA[comp.tipo]
    clave = _clave_venta(comp.tp_id_cliente, comp.id_contraparte, tipo, EMISION_VENTAS)
    nodo = next((v for v in ventas.lista("detalleVentas")
                 if _clave_venta(v.texto("tpIdCliente"), v.texto("idCliente"), v.texto("tipoComprobante"),
                                 v.texto("tipoEmision")) == clave), None)
    defn = doc.esquema.raiz.buscar("detalleVentas")
    if nodo is None:
        nodo = crear_vacio(defn)
        valores = {"tpIdCliente": comp.tp_id_cliente, "idCliente": comp.id_contraparte, "tipoComprobante": tipo,
                   "tipoEmision": EMISION_VENTAS, "numeroComprobantes": "0"}
        if comp.tp_id_cliente in ("04", "05", "06"):
            valores["parteRelVtas"] = "NO"
        if comp.tp_id_cliente == "06":
            valores["tipoCliente"] = "01"
            valores["denoCli"] = _solo_letras(comp.razon_contraparte)
        for campo in ("baseNoGraIva", "baseImponible", "baseImpGrav", "montoIva", "montoIce", "valorRetIva",
                      "valorRetRenta"):
            valores[campo] = "0.00"
        for campo, valor in valores.items():
            if defn.hijo(campo) is not None:
                nodo.poner(campo, valor)
        ventas.agregar("detalleVentas", nodo)

    def sumar(campo: str, monto: Decimal) -> None:
        if defn.hijo(campo) is not None:
            actual = _dec(nodo.texto(campo))
            nodo.poner(campo, _monto(actual + monto))

    nodo.poner("numeroComprobantes", str(int(nodo.texto("numeroComprobantes") or 0) + 1))
    sumar("baseNoGraIva", comp.base_no_objeto + comp.base_exenta)
    sumar("baseImponible", comp.base_cero)
    sumar("baseImpGrav", comp.base_gravada)
    sumar("montoIva", comp.iva)
    sumar("montoIce", comp.ice)
    if comp.formas_pago and defn.hijo("formasDePago") is not None:
        fp = nodo.hijo("formasDePago") or nodo.agregar("formasDePago")
        actuales = [h.valor for h in fp.lista("formaPago") if h.valor]
        for h in list(fp.hijos):
            if not h.valor:
                fp.eliminar(h)
        for codigo in comp.formas_pago:
            if codigo not in actuales:
                fp.agregar("formaPago").valor = codigo
                actuales.append(codigo)
    return nodo


def _actualizar_establecimientos(doc: Documento, por_estab: dict[str, Decimal]) -> None:
    """Suma las ventas importadas a cada establecimiento y recalcula el total de ventas."""
    from .reglas import total_ventas

    raiz = doc.raiz
    if raiz.defn.hijo("ventasEstablecimiento") is not None:
        cont = _contenedor(raiz, "ventasEstablecimiento")
        defn = doc.esquema.raiz.buscar("ventaEst")
        for estab, monto in sorted(por_estab.items()):
            ve = next((e for e in cont.lista("ventaEst") if e.texto("codEstab") == estab), None)
            if ve is None:
                ve = crear_vacio(defn)
                ve.poner("codEstab", estab)
                ve.poner("ventasEstab", "0.00")
                if defn.hijo("ivaComp") is not None:
                    ve.poner("ivaComp", "0.00")
                cont.agregar("ventaEst", ve)
            ve.poner("ventasEstab", _monto(_dec(ve.texto("ventasEstab")) + monto))
    raiz.poner("totalVentas", _monto(total_ventas(raiz)))


def _solo_letras(texto: str) -> str:
    import re
    import unicodedata

    sin = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^A-Za-z0-9]+", " ", sin).split()).upper()[:500]


def parece_anexo(ruta: Path) -> bool:
    if ruta.suffix.lower() == ".pdf":
        return False
    """¿El archivo es un anexo ATS (raíz <iva>) en vez de un comprobante?"""
    try:
        if ruta.suffix.lower() == ".zip":
            with zipfile.ZipFile(ruta) as z:
                xmls = [n for n in z.namelist() if n.lower().endswith(".xml")]
                if len(xmls) != 1:
                    return False
                cabeza = z.open(xmls[0]).read(400)
        else:
            with open(ruta, "rb") as f:
                cabeza = f.read(400)
    except (OSError, zipfile.BadZipFile, KeyError):
        return False
    texto = cabeza.decode("utf-8", "ignore").lstrip("﻿")
    if texto.startswith("<?xml"):
        texto = texto[texto.find("?>") + 2:]
    return texto.lstrip().startswith("<iva")
