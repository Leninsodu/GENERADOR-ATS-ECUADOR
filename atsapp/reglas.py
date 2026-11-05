"""Reglas de negocio del ATS, escritas a partir de la ficha técnica del SRI.

Cada regla indica entre corchetes la sección de la ficha en la que se basa.
Las reglas que la ficha expresa como obligatorias generan errores; las que son
solo comprobaciones de coherencia (o donde el SRI tiene excepciones conocidas)
generan advertencias.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from .catalogos import Catalogos, rango_periodo
from .documento import Documento, Nodo
from .identificacion import CONSUMIDOR_FINAL, cedula_valida, ruc_aceptado, ruc_en_clave_acceso
from .validacion import Mensaje, Severidad

E, A = Severidad.ERROR, Severidad.ADVERTENCIA

# Comprobantes de venta que restan del total de ventas (notas de crédito) y los que suman.
# Los demás tipos no entran en el total. Desde enero de 2016 solo cuentan los registros
# con emisión física (F): las ventas electrónicas (E) no se suman (así valida DIMM).
COMPROBANTES_QUE_RESTAN = {"04", "51", "372"}
COMPROBANTES_QUE_SUMAN = {"05", "18", "44", "49", "50", "52", "370", "371", "373"}
DESDE_SOLO_FISICAS = (2016, 1)
# Notas de crédito: no llevan formas de pago (si las llevan, DIMM lo marca como error)
NOTAS_DE_CREDITO = {"04", "47", "51"}
FECHA_CAMBIO_UMBRAL_PAGO = dt.date(2023, 12, 20)
TOLERANCIA_IVA = Decimal("0.05")


def signo_en_total(venta: Nodo, anio: int | None, mes: int | None) -> int:
    """+1 si el registro suma al total de ventas, -1 si resta, 0 si no cuenta."""
    if anio and mes and (anio, mes) >= DESDE_SOLO_FISICAS and venta.texto("tipoEmision") != "F":
        return 0
    tipo = venta.texto("tipoComprobante")
    if tipo in COMPROBANTES_QUE_SUMAN:
        return 1
    if tipo in COMPROBANTES_QUE_RESTAN:
        return -1
    return 0


def total_ventas(raiz: Nodo) -> Decimal:
    """Total de ventas como lo calcula DIMM: bases (no objeto + 0% + gravada) de los registros que cuentan."""
    try:
        anio, mes = int(raiz.texto("Anio")), int(raiz.texto("Mes"))
    except ValueError:
        anio = mes = None
    total = Decimal(0)
    ventas = raiz.hijo("ventas")
    for v in ventas.lista("detalleVentas") if ventas is not None else []:
        base = sum((dec(v.texto(k)) for k in ("baseNoGraIva", "baseImponible", "baseImpGrav")), Decimal(0))
        total += signo_en_total(v, anio, mes) * base
    return total


def dec(texto: str) -> Decimal:
    try:
        return Decimal(texto) if texto else Decimal(0)
    except InvalidOperation:
        return Decimal(0)


def fecha(texto: str) -> dt.date | None:
    try:
        return dt.datetime.strptime(texto, "%d/%m/%Y").date()
    except (ValueError, TypeError):
        return None


def aplicar_reglas(doc: Documento, catalogos: Catalogos | None) -> list[Mensaje]:
    r = _Reglas(doc, catalogos)
    r.cabecera()
    r.compras()
    r.ventas()
    r.ventas_establecimiento()
    return r.mensajes


class _Reglas:
    def __init__(self, doc: Documento, catalogos: Catalogos | None):
        self.doc = doc
        self.raiz = doc.raiz
        self.cat = catalogos
        self.mensajes: list[Mensaje] = []
        semestral = self.raiz.texto("regimenMicroempresa") == "SI"
        self.inicio, self.fin = rango_periodo(doc.anio, doc.mes, semestral)

    def msg(self, sev: Severidad, nodo: Nodo, texto: str, campo: str | None = None) -> None:
        objetivo = nodo.hijo(campo) if campo else None
        ruta = objetivo.ruta() if objetivo is not None else nodo.ruta() + (f"/{campo}" if campo else "")
        self.mensajes.append(Mensaje(sev, ruta, texto))

    # --- cabecera [2.1 Informante] -------------------------------------------------
    def cabecera(self) -> None:
        r = self.raiz
        ruc = r.texto("IdInformante")
        if len(ruc) == 13 and ruc.isdigit() and not ruc_aceptado(ruc):
            self.msg(E, r, "El RUC del informante no es válido (la cédula que contiene no cumple el dígito verificador).", "IdInformante")
        if self.doc.anio is not None and self.doc.anio < 2002:
            self.msg(E, r, "Solo se aceptan períodos desde el año 2002.", "Anio")
        if r.texto("regimenMicroempresa") and r.texto("Mes") not in ("06", "12"):
            self.msg(E, r, "La declaración semestral (RIMPE) solo aplica con mes 06 o 12.", "regimenMicroempresa")
        if r.texto("numEstabRuc") == "000":
            self.msg(E, r, "El número de establecimientos debe ser mayor a 000.", "numEstabRuc")

    # --- compras [2.2 Compras] ------------------------------------------------------
    def compras(self) -> None:
        nodo = self.raiz.hijo("compras")
        if nodo is None:
            return
        vistos: dict[tuple, Nodo] = {}
        for c in nodo.lista("detalleCompras"):
            self._identificacion(c, "tpIdProv", "idProv", {"01": "ruc", "02": "cedula"})
            self._comprobante_y_sustento(c)
            self._fechas_compra(c)
            self._iva(c, fecha(c.texto("fechaEmision")))
            self._retenciones_iva(c)
            self._forma_pago(c)
            clave = tuple(c.texto(k) for k in ("tpIdProv", "idProv", "tipoComprobante", "establecimiento", "puntoEmision", "secuencial"))
            if all(clave):
                if clave in vistos:
                    otro = vistos[clave].indice_entre_iguales()
                    self.msg(E, c, f"Comprobante duplicado: es igual a la compra n.º {otro} (proveedor, tipo, serie y secuencial).")
                else:
                    vistos[clave] = c

    def _identificacion(self, n: Nodo, campo_tipo: str, campo_id: str, tipos: dict[str, str]) -> None:
        tipo, ident = n.texto(campo_tipo), n.texto(campo_id)
        if not ident:
            return
        clase = tipos.get(tipo)
        if clase == "ruc":
            if len(ident) != 13 or not ident.isdigit():
                self.msg(E, n, "El RUC debe tener 13 dígitos.", campo_id)
            elif ident[10:] != "001":
                self.msg(E, n, f"El RUC {ident} debe terminar en 001.", campo_id)
            elif not ruc_aceptado(ident) and ruc_en_clave_acceso(n.texto("autorizacion")) != ident:
                # mismo criterio que DIMM: en personas naturales la cédula debe ser válida
                self.msg(E, n, f"El RUC {ident} no es válido: la cédula que contiene no cumple el dígito verificador.", campo_id)
        elif clase == "cedula":
            if len(ident) != 10 or not ident.isdigit():
                self.msg(E, n, "La cédula debe tener 10 dígitos.", campo_id)
            elif not cedula_valida(ident):
                self.msg(E, n, f"La cédula {ident} no es válida (dígito verificador).", campo_id)
        elif clase == "consumidor_final":
            if ident != CONSUMIDOR_FINAL:
                self.msg(E, n, f"Para consumidor final la identificación debe ser {CONSUMIDOR_FINAL}.", campo_id)
        if ident.isdigit() and len(set(ident)) == 1 and clase != "consumidor_final":
            self.msg(E, n, "La identificación no puede ser una secuencia de un mismo dígito.", campo_id)

    def _comprobante_y_sustento(self, c: Nodo) -> None:
        """[Tabla 4] el tipo de comprobante debe admitir el tipo de identificación y el sustento."""
        if self.cat is None:
            return
        tabla = self.cat.tablas.get("t4_comprobantes")
        tipo = c.texto("tipoComprobante")
        fila = tabla.buscar(tipo) if tabla else None
        if fila is None or len(fila.extra) < 2:
            return
        transacciones, sustentos = fila.extra[0] or [], fila.extra[1] or []
        tp = c.texto("tpIdProv")
        if tp and tp not in transacciones:
            self.msg(E, c, f"El comprobante tipo {tipo} ({fila.descripcion}) no se acepta para el tipo de identificación {tp}.", "tipoComprobante")
        cs = c.texto("codSustento")
        if cs and sustentos and cs not in sustentos:
            self.msg(E, c, f"El sustento {cs} no es válido para el comprobante tipo {tipo}. Válidos: {', '.join(sustentos)}.", "codSustento")
        elif cs and not sustentos:
            self.msg(A, c, f"El comprobante tipo {tipo} ({fila.descripcion}) no se usa normalmente en compras.", "tipoComprobante")

    def _fechas_compra(self, c: Nodo) -> None:
        """[2.2] La fecha de registro debe estar en el período y ser >= la fecha de emisión."""
        f_reg, f_emi = fecha(c.texto("fechaRegistro")), fecha(c.texto("fechaEmision"))
        minimo = dt.date(2002, 1, 1)
        if f_reg and self.inicio and not (self.inicio <= f_reg <= self.fin):
            self.msg(E, c, "La fecha de registro contable debe estar dentro del período informado.", "fechaRegistro")
        if f_emi and self.fin and f_emi > self.fin:
            self.msg(E, c, "La fecha de emisión no puede ser posterior al período informado.", "fechaEmision")
        if f_reg and f_emi and f_reg < f_emi:
            self.msg(E, c, "La fecha de registro debe ser mayor o igual a la fecha de emisión.", "fechaRegistro")
        for campo, f in (("fechaRegistro", f_reg), ("fechaEmision", f_emi)):
            if f and f < minimo:
                self.msg(E, c, "La fecha debe ser posterior al 01/01/2002.", campo)

    def _iva(self, n: Nodo, fecha_ref: dt.date | None) -> None:
        """Coherencia entre la base gravada y el IVA según las tarifas vigentes (solo advertencia)."""
        if self.cat is None:
            return
        base, iva = dec(n.texto("baseImpGrav")), dec(n.texto("montoIva"))
        if base <= 0 and iva <= 0:
            return
        if base <= 0 < iva:
            self.msg(A, n, "Hay monto de IVA pero la base gravada es cero.", "montoIva")
            return
        fecha_ref = fecha_ref or self.fin
        if fecha_ref is None:
            return
        tarifas = self.cat.tarifas_en(fecha_ref)
        if tarifas and not any(abs(base * t / 100 - iva) <= TOLERANCIA_IVA for t in tarifas):
            pct = (iva / base * 100).quantize(Decimal("0.01"))
            esperado = ", ".join(f"{t}% = {(base * t / 100).quantize(Decimal('0.01'))}" for t in tarifas)
            self.msg(A, n, f"El IVA ({iva}) equivale al {pct}% de la base gravada; con las tarifas vigentes sería {esperado}.", "montoIva")

    def _retenciones_iva(self, c: Nodo) -> None:
        campos = ("valRetBien10", "valRetServ20", "valorRetBienes", "valRetServ50", "valorRetServicios", "valRetServ100")
        total = sum((dec(c.texto(k)) for k in campos), Decimal(0))
        iva = dec(c.texto("montoIva"))
        if total > iva + TOLERANCIA_IVA:
            self.msg(A, c, f"Las retenciones de IVA ({total}) superan el monto de IVA ({iva}).", "montoIva")

    def _forma_pago(self, c: Nodo) -> None:
        """[2.2 Forma de pago] obligatoria si bases + impuestos > 500 (> 1000 antes del 20/12/2023)."""
        campos = ("baseNoGraIva", "baseImponible", "baseImpGrav", "baseImpExe", "montoIce", "montoIva")
        total = sum((dec(c.texto(k)) for k in campos), Decimal(0))
        ref = fecha(c.texto("fechaEmision")) or self.fin
        umbral = Decimal(500) if ref is None or ref >= FECHA_CAMBIO_UMBRAL_PAGO else Decimal(1000)
        formas = c.hijo("formasDePago")
        tiene = formas is not None and any(h.valor for h in formas.lista("formaPago"))
        if c.texto("tipoComprobante") in NOTAS_DE_CREDITO:
            if tiene:
                self.msg(E, c, "Las formas de pago no aplican para notas de crédito.", "formasDePago")
            return
        if total > umbral and not tiene:
            self.msg(E, c, f"La compra suma {total} (más de USD {umbral}); debe registrar al menos una forma de pago.", "formasDePago")

    # --- ventas [2.3 Ventas] ---------------------------------------------------------
    def ventas(self) -> None:
        nodo = self.raiz.hijo("ventas")
        hay_ventas = False
        if nodo is not None:
            vistos: dict[tuple, Nodo] = {}
            for v in nodo.lista("detalleVentas"):
                hay_ventas = True
                self._identificacion(v, "tpIdCliente", "idCliente", {"04": "ruc", "05": "cedula", "07": "consumidor_final"})
                self._comprobante_venta(v)
                self._iva(v, self.fin)
                if v.texto("parteRelVtas") == "" and v.texto("tpIdCliente") in ("04", "05", "06"):
                    self.msg(E, v, "Debe indicar si el cliente es parte relacionada (SI/NO).", "parteRelVtas")
                formas = v.hijo("formasDePago")
                tiene_formas = formas is not None and any(h.valor for h in formas.lista("formaPago"))
                if v.texto("tipoComprobante") in NOTAS_DE_CREDITO:
                    if tiene_formas:
                        self.msg(E, v, "Las formas de cobro no aplican para notas de crédito.", "formasDePago")
                elif not tiene_formas:
                    self.msg(E, v, "Debe registrar al menos una forma de cobro.", "formasDePago")
                clave = tuple(v.texto(k) for k in ("tpIdCliente", "idCliente", "tipoComprobante", "tipoEmision"))
                if all(clave[:3]):
                    if clave in vistos:
                        otro = vistos[clave].indice_entre_iguales()
                        self.msg(E, v, f"Registro repetido: igual a la venta n.º {otro} (cliente, tipo de comprobante y tipo de emisión). Debe consolidarse en un solo registro.")
                    else:
                        vistos[clave] = v
        total_calc = total_ventas(self.raiz)
        declarado = self.raiz.texto("totalVentas")
        if declarado and (hay_ventas or dec(declarado) != 0):
            diferencia = abs(dec(declarado) - total_calc)
            if diferencia:
                electronicas = nodo is not None and any(v.texto("tipoEmision") == "E" for v in nodo.lista("detalleVentas"))
                nota = (" Las ventas con emisión electrónica (E) no se suman: DIMM solo cuenta las de emisión física (F)."
                        if electronicas else "")
                self.msg(E if diferencia > 1 else A, self.raiz,
                         f"El total de ventas ({declarado}) no coincide con la suma de las ventas ({total_calc}).{nota}",
                         "totalVentas")
        self.total_ventas_calculado = total_calc

    def _comprobante_venta(self, v: Nodo) -> None:
        if self.cat is None:
            return
        tabla = self.cat.tablas.get("t4_comprobantes")
        tipo = v.texto("tipoComprobante")
        fila = tabla.buscar(tipo) if tabla else None
        tp = v.texto("tpIdCliente")
        if fila is not None and fila.extra and tp and tp not in (fila.extra[0] or []):
            self.msg(E, v, f"El comprobante tipo {tipo} ({fila.descripcion}) no se acepta en ventas con tipo de identificación {tp}.", "tipoComprobante")

    # --- ventas por establecimiento [2.4] ---------------------------------------------
    def ventas_establecimiento(self) -> None:
        nodo = self.raiz.hijo("ventasEstablecimiento")
        ests = nodo.lista("ventaEst") if nodo is not None else []
        num = self.raiz.texto("numEstabRuc")
        if not ests:
            if self.raiz.hijo("ventas") is not None and self.raiz.hijo("ventas").lista("detalleVentas"):
                self.msg(A, self.raiz, "Hay ventas registradas pero no se informaron las ventas por establecimiento.", "ventasEstablecimiento")
            return
        codigos = defaultdict(list)
        total = Decimal(0)
        for e in ests:
            codigos[e.texto("codEstab")].append(e)
            total += dec(e.texto("ventasEstab"))
        for cod, lista in codigos.items():
            if cod and len(lista) > 1:
                for e in lista[1:]:
                    self.msg(E, e, f"El establecimiento {cod} está repetido.", "codEstab")
        if num.isdigit() and int(num) != len(ests):
            self.msg(E, self.raiz, f"Se declararon {int(num)} establecimiento(s) en el RUC pero hay {len(ests)} registro(s) de ventas por establecimiento; deben ser iguales.", "numEstabRuc")
        declarado = dec(self.raiz.texto("totalVentas"))
        diferencia = abs(total - declarado)
        if diferencia:
            self.msg(E if diferencia > 1 else A, nodo,
                     f"La suma de ventas por establecimiento ({total}) no es igual al total de ventas ({declarado}).")
