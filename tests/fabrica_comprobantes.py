"""Genera XML de comprobantes electrónicos de prueba (datos ficticios) con el formato del SRI."""

INFORMANTE = "1799999907001"  # RUC ficticios (cumplen el dígito verificador)
PROVEEDOR = "1799999915001"
CLIENTE = "1799999923001"


def _info_tributaria(cod_doc, ruc=PROVEEDOR, estab="001", pto="002", sec="000000123", ambiente="2"):
    clave = ("10052026" + cod_doc + ruc + ambiente + estab + pto + sec + "12345678" + "1" + "7")[:49].ljust(49, "0")
    return (f"<infoTributaria><ambiente>{ambiente}</ambiente><tipoEmision>1</tipoEmision>"
            f"<razonSocial>PROVEEDOR DE PRUEBA S.A.</razonSocial><ruc>{ruc}</ruc><claveAcceso>{clave}</claveAcceso>"
            f"<codDoc>{cod_doc}</codDoc><estab>{estab}</estab><ptoEmi>{pto}</ptoEmi><secuencial>{sec}</secuencial>"
            f"<dirMatriz>QUITO</dirMatriz></infoTributaria>")


def _impuestos(etiqueta, filas):
    return "".join(f"<{etiqueta}><codigo>{c}</codigo><codigoPorcentaje>{p}</codigoPorcentaje>"
                   f"<baseImponible>{b}</baseImponible><valor>{v}</valor></{etiqueta}>" for c, p, b, v in filas)


def factura(fecha="10/05/2026", comprador=INFORMANTE, sec="000000123", impuestos=(("2", "4", "100.00", "15.00"), ("2", "0", "20.00", "0.00")),
            pagos=("20",), total="135.00", ruc=PROVEEDOR, ambiente="2", firma=False):
    pagos_xml = "".join(f"<pago><formaPago>{p}</formaPago><total>{total}</total></pago>" for p in pagos)
    firma_xml = '<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#"><ds:SignedInfo/></ds:Signature>' if firma else ""
    return (f'<?xml version="1.0" encoding="UTF-8"?><factura id="comprobante" version="2.1.0">'
            + _info_tributaria("01", ruc=ruc, sec=sec, ambiente=ambiente) +
            f"<infoFactura><fechaEmision>{fecha}</fechaEmision><obligadoContabilidad>SI</obligadoContabilidad>"
            f"<tipoIdentificacionComprador>04</tipoIdentificacionComprador><razonSocialComprador>EMPRESA PRUEBA</razonSocialComprador>"
            f"<identificacionComprador>{comprador}</identificacionComprador><totalSinImpuestos>120.00</totalSinImpuestos>"
            f"<totalDescuento>0.00</totalDescuento><totalConImpuestos>{_impuestos('totalImpuesto', impuestos)}</totalConImpuestos>"
            f"<propina>0.00</propina><importeTotal>{total}</importeTotal><moneda>DOLAR</moneda><pagos>{pagos_xml}</pagos></infoFactura>"
            f"<detalles><detalle><descripcion>Servicio</descripcion></detalle></detalles>{firma_xml}</factura>")


def sobre(comprobante: str, estado="AUTORIZADO", numero=None):
    numero = numero or clave_acceso(fecha="10052026", ruc=PROVEEDOR, serie="001002", sec="000000123")
    return (f'<?xml version="1.0" encoding="UTF-8"?><autorizacion><estado>{estado}</estado>'
            f"<numeroAutorizacion>{numero}</numeroAutorizacion><fechaAutorizacion>2026-05-10T10:00:00-05:00</fechaAutorizacion>"
            f"<ambiente>PRODUCCIÓN</ambiente><comprobante><![CDATA[{comprobante}]]></comprobante><mensajes/></autorizacion>")


def nota_credito(mod_sec="000000123", fecha="15/05/2026"):
    return (f'<?xml version="1.0" encoding="UTF-8"?><notaCredito id="comprobante" version="1.1.0">'
            + _info_tributaria("04", sec="000000045") +
            f"<infoNotaCredito><fechaEmision>{fecha}</fechaEmision><tipoIdentificacionComprador>04</tipoIdentificacionComprador>"
            f"<razonSocialComprador>EMPRESA PRUEBA</razonSocialComprador><identificacionComprador>{INFORMANTE}</identificacionComprador>"
            f"<codDocModificado>01</codDocModificado><numDocModificado>001-002-{mod_sec}</numDocModificado>"
            f"<fechaEmisionDocSustento>10/05/2026</fechaEmisionDocSustento><totalSinImpuestos>10.00</totalSinImpuestos>"
            f"<valorModificacion>11.50</valorModificacion><moneda>DOLAR</moneda>"
            f"<totalConImpuestos>{_impuestos('totalImpuesto', [('2', '4', '10.00', '1.50')])}</totalConImpuestos>"
            f"<motivo>Devolución</motivo></infoNotaCredito></notaCredito>")


def liquidacion(cedula, fecha="12/05/2026"):
    return (f'<?xml version="1.0" encoding="UTF-8"?><liquidacionCompra id="comprobante" version="1.1.0">'
            + _info_tributaria("03", ruc=INFORMANTE, sec="000000007") +
            f"<infoLiquidacionCompra><fechaEmision>{fecha}</fechaEmision><tipoIdentificacionProveedor>05</tipoIdentificacionProveedor>"
            f"<razonSocialProveedor>JUAN PÉREZ</razonSocialProveedor><identificacionProveedor>{cedula}</identificacionProveedor>"
            f"<totalSinImpuestos>50.00</totalSinImpuestos><totalDescuento>0.00</totalDescuento>"
            f"<totalConImpuestos>{_impuestos('totalImpuesto', [('2', '0', '50.00', '0.00')])}</totalConImpuestos>"
            f"<importeTotal>50.00</importeTotal><moneda>DOLAR</moneda><pagos><pago><formaPago>01</formaPago><total>50.00</total></pago></pagos>"
            f"</infoLiquidacionCompra></liquidacionCompra>")


def retencion():
    return ('<?xml version="1.0" encoding="UTF-8"?><comprobanteRetencion id="comprobante" version="2.0.0">'
            + _info_tributaria("07") + "<infoCompRetencion/></comprobanteRetencion>")


def clave_acceso(fecha="05052026", tipo="01", ruc=INFORMANTE, serie="001002", sec="000000466"):
    base = fecha + tipo + ruc + "2" + serie + sec + "12345678" + "1"
    suma, peso = 0, 2
    for d in reversed(base):
        suma += int(d) * peso
        peso = 2 if peso == 7 else peso + 1
    v = 11 - suma % 11
    return base + str(0 if v == 11 else 1 if v == 10 else v)


def texto_ride(cliente=CLIENTE, nombre="CLIENTE DE PRUEBA S.A.", grav="900.00", cero="90.00", iva="135.00",
               total="1125.00", sec="000000466", fecha="05052026", tipo="01"):
    """Texto como lo extrae pypdf en modo 'layout' de un RIDE del facturador del SRI."""
    clave = clave_acceso(fecha=fecha, tipo=tipo, sec=sec)
    return f"""
                     R.U.C.:   {INFORMANTE}
                     FACTURA
                     No.   001-002-{sec}
                     NÚMERO DE AUTORIZACIÓN
                     {clave}
  Empresa Prueba     AMBIENTE:   PRODUCCIÓN
Razón Social / Nombres y Apellidos:      {nombre}
Identificación              {cliente}
Fecha                       {fecha[:2]}/{fecha[2:4]}/{fecha[4:]}       Placa / Matrícula:     Guía
Información Adicional                               SUBTOTAL 15%            {grav}
Dirección:   CALLE 1                                SUBTOTAL 0%             {cero}
Email:   a@b.ec                                     SUBTOTAL NO OBJETO DE IVA   0.00
                                                    SUBTOTAL EXENTO DE IVA      0.00
Forma de pago                 Valor
                                                    SUBTOTAL SIN IMPUESTOS      990.00
20 - OTROS CON UTILIZACION DEL SISTEMA   {total}
                                                    ICE                         0.00
                                                    IVA 15%                     {iva}
                                                    PROPINA                     0.00
                                                    VALOR TOTAL                 {total}
                                                    VALOR TOTAL SIN SUBSIDIO    0.00
"""


def retencion_v2(agente, retenido, num_doc, lineas, cod_doc="01", sec="000000010", periodo="05/2026",
                 fecha="12/05/2026", ruc_clave=None):
    """lineas: [(codigo impuesto, codigoRetencion, base, porcentaje, valor)]"""
    clave = clave_acceso(fecha=fecha.replace("/", ""), tipo="07", ruc=ruc_clave or agente, serie="001001", sec=sec)
    rets = "".join(f"<retencion><codigo>{c}</codigo><codigoRetencion>{cr}</codigoRetencion><baseImponible>{b}</baseImponible>"
                   f"<porcentajeRetener>{p}</porcentajeRetener><valorRetenido>{v}</valorRetenido></retencion>"
                   for c, cr, b, p, v in lineas)
    return (f'<?xml version="1.0" encoding="UTF-8"?><comprobanteRetencion id="comprobante" version="2.0.0">'
            f"<infoTributaria><ambiente>2</ambiente><tipoEmision>1</tipoEmision><razonSocial>AGENTE</razonSocial>"
            f"<ruc>{agente}</ruc><claveAcceso>{clave}</claveAcceso><codDoc>07</codDoc><estab>001</estab><ptoEmi>001</ptoEmi>"
            f"<secuencial>{sec}</secuencial><dirMatriz>QUITO</dirMatriz></infoTributaria>"
            f"<infoCompRetencion><fechaEmision>{fecha}</fechaEmision><tipoIdentificacionSujetoRetenido>04</tipoIdentificacionSujetoRetenido>"
            f"<parteRel>NO</parteRel><razonSocialSujetoRetenido>RETENIDO</razonSocialSujetoRetenido>"
            f"<identificacionSujetoRetenido>{retenido}</identificacionSujetoRetenido><periodoFiscal>{periodo}</periodoFiscal></infoCompRetencion>"
            f"<docsSustento><docSustento><codSustento>01</codSustento><codDocSustento>{cod_doc}</codDocSustento>"
            f"<numDocSustento>{num_doc}</numDocSustento><fechaEmisionDocSustento>10/05/2026</fechaEmisionDocSustento>"
            f"<pagoLocExt>01</pagoLocExt><retenciones>{rets}</retenciones></docSustento></docsSustento></comprobanteRetencion>")


def retencion_v1(agente, retenido, num_doc, lineas, sec="000000011"):
    clave = clave_acceso(fecha="12052026", tipo="07", ruc=agente, serie="001001", sec=sec)
    imps = "".join(f"<impuesto><codigo>{c}</codigo><codigoRetencion>{cr}</codigoRetencion><baseImponible>{b}</baseImponible>"
                   f"<porcentajeRetener>{p}</porcentajeRetener><valorRetenido>{v}</valorRetenido><codDocSustento>01</codDocSustento>"
                   f"<numDocSustento>{num_doc}</numDocSustento><fechaEmisionDocSustento>10/05/2026</fechaEmisionDocSustento></impuesto>"
                   for c, cr, b, p, v in lineas)
    return (f'<?xml version="1.0" encoding="UTF-8"?><comprobanteRetencion id="comprobante" version="1.0.0">'
            f"<infoTributaria><ambiente>2</ambiente><tipoEmision>1</tipoEmision><razonSocial>AGENTE</razonSocial><ruc>{agente}</ruc>"
            f"<claveAcceso>{clave}</claveAcceso><codDoc>07</codDoc><estab>001</estab><ptoEmi>001</ptoEmi><secuencial>{sec}</secuencial>"
            f"<dirMatriz>QUITO</dirMatriz></infoTributaria><infoCompRetencion><fechaEmision>12/05/2026</fechaEmision>"
            f"<tipoIdentificacionSujetoRetenido>04</tipoIdentificacionSujetoRetenido><razonSocialSujetoRetenido>X</razonSocialSujetoRetenido>"
            f"<identificacionSujetoRetenido>{retenido}</identificacionSujetoRetenido><periodoFiscal>05/2026</periodoFiscal>"
            f"</infoCompRetencion><impuestos>{imps}</impuestos></comprobanteRetencion>")


def texto_ride_retencion(agente, retenido, num_doc="001002000000123", sec="000000012"):
    clave = clave_acceso(fecha="12052026", tipo="07", ruc=agente, serie="001001", sec=sec)
    return f"""
                     R.U.C.:   {agente}
                     COMPROBANTE DE RETENCIÓN
                     No.   001-001-{sec}
                     NÚMERO DE AUTORIZACIÓN
                     {clave}
                     AMBIENTE:   PRODUCCIÓN
Razón Social / Nombres y Apellidos:      PROVEEDOR DE PRUEBA S.A.
Identificación              {retenido}
Fecha Emisión               12/05/2026
 Comprobante   Número            Fecha Emisión   Ejercicio Fiscal   Base Imponible   Impuesto   Código   Porcentaje   Valor Retenido
 FACTURA       {num_doc}   10/05/2026      05/2026            100.00           RENTA      312      1.75         1.75
 FACTURA       {num_doc}   10/05/2026      05/2026            15.00            IVA        1        30.00        4.50
"""
