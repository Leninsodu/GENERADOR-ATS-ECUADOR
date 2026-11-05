from decimal import Decimal

from fabrica_comprobantes import (CLIENTE, INFORMANTE, PROVEEDOR, factura, retencion_v1, retencion_v2, sobre, texto_ride,
                                  texto_ride_retencion)
from test_nucleo import _doc_minimo

from atsapp import comprobantes, retenciones
from atsapp.comprobantes import AVISO, OK, OMITIR, comprobante_desde_texto_ride, leer_bytes
from atsapp.validacion import validar_documento, validar_xsd



def _con_compra(esquema):
    doc = _doc_minimo(esquema)
    comprobantes.importar(doc, comprobantes.analizar(doc, [leer_bytes(sobre(factura(sec="000000123")).encode())]))
    return doc


def test_lee_v1_y_v2():
    r2 = leer_bytes(retencion_v2(INFORMANTE, PROVEEDOR, "001002000000123", [("1", "312", "100.00", "1.75", "1.75")]).encode())
    r1 = leer_bytes(retencion_v1(INFORMANTE, PROVEEDOR, "001002000000123", [("2", "1", "15.00", "30.00", "4.50")]).encode())
    assert isinstance(r2, retenciones.Retencion) and isinstance(r1, retenciones.Retencion)
    assert r2.lineas[0].serie_sustento == ("001", "002", "000000123")
    assert r1.total_iva == Decimal("4.50") and r2.total_renta == Decimal("1.75")


def test_retencion_emitida_va_a_la_compra(esquema, catalogos):
    doc = _con_compra(esquema)
    ret = leer_bytes(retencion_v2(INFORMANTE, PROVEEDOR, "001002000000123",
                                  [("1", "312", "120.00", "1.75", "2.10"), ("2", "1", "15.00", "30.00", "4.50")]).encode())
    props = retenciones.analizar(doc, [ret])
    assert props[0].destino == "compras" and props[0].estado == OK
    res = retenciones.aplicar(doc, props)
    c = res.compras[0]
    assert c.texto("valorRetBienes") == "4.50"
    air = c.hijo("air").lista("detalleAir")
    assert [(a.texto("codRetAir"), a.texto("baseImpAir"), a.texto("porcentajeAir"), a.texto("valRetAir")) for a in air] == \
        [("312", "120.00", "1.75", "2.10")]
    assert (c.texto("estabRetencion1"), c.texto("ptoEmiRetencion1"), c.texto("secRetencion1")) == ("001", "001", "000000010")
    assert len(c.texto("autRetencion1")) == 49 and c.texto("fechaEmiRet1") == "12/05/2026"
    assert validar_xsd(doc) == []
    assert [m.texto for m in validar_documento(doc, catalogos) if m.es_error] == []
    # segunda vez: ya registrada
    assert retenciones.analizar(doc, [ret])[0].estado == OMITIR


def test_retencion_de_compra_inexistente(esquema):
    doc = _doc_minimo(esquema)
    ret = leer_bytes(retencion_v2(INFORMANTE, PROVEEDOR, "001002000000999", [("2", "1", "15.00", "30.00", "4.50")]).encode())
    p = retenciones.analizar(doc, [ret])[0]
    assert p.estado == OMITIR and "importe primero la factura" in p.notas[0]


def test_retencion_y_factura_en_el_mismo_lote(esquema):
    doc = _doc_minimo(esquema)
    fac = leer_bytes(factura(sec="000000124").encode())
    ret = leer_bytes(retencion_v2(INFORMANTE, PROVEEDOR, "001002000000124", [("2", "1", "15.00", "30.00", "4.50")]).encode())
    props = comprobantes.analizar(doc, [fac])
    pr = retenciones.analizar(doc, [ret], props)
    assert pr[0].estado == OK
    comprobantes.importar(doc, props)
    assert retenciones.aplicar(doc, pr).compras


def test_retencion_recibida_va_a_ventas(esquema, catalogos):
    doc = _doc_minimo(esquema)
    venta = comprobante_desde_texto_ride(texto_ride(cliente=CLIENTE))
    comprobantes.importar(doc, comprobantes.analizar(doc, [venta]))
    ret = leer_bytes(retencion_v2(CLIENTE, INFORMANTE, "001002000000466",
                                  [("2", "2", "135.00", "70.00", "94.50"), ("1", "320", "990.00", "10.00", "99.00")]).encode())
    props = retenciones.analizar(doc, [ret])
    assert props[0].destino == "ventas" and props[0].estado == OK
    res = retenciones.aplicar(doc, props)
    v = res.ventas[0]
    assert (v.texto("valorRetIva"), v.texto("valorRetRenta")) == ("94.50", "99.00")
    assert [m.texto for m in validar_documento(doc, catalogos) if m.es_error] == []
    again = retenciones.analizar(doc, [ret], ya_importadas=set(res.claves_ventas))[0]
    assert again.ya_registrado and not again.seleccionado


def test_retencion_recibida_sin_venta_o_de_otro_periodo(esquema):
    doc = _doc_minimo(esquema)
    ret = leer_bytes(retencion_v2(CLIENTE, INFORMANTE, "001002000000466", [("2", "2", "135.00", "70.00", "94.50")]).encode())
    assert retenciones.analizar(doc, [ret])[0].estado == OMITIR
    ret2 = leer_bytes(retencion_v2(CLIENTE, INFORMANTE, "001002000000466", [("2", "2", "1", "70.00", "0.70")],
                                   periodo="04/2026").encode())
    assert "período 04/2026" in retenciones.analizar(doc, [ret2])[0].notas[0]


def test_retencion_desde_pdf(esquema):
    ret = comprobante_desde_texto_ride(texto_ride_retencion(INFORMANTE, PROVEEDOR))
    assert isinstance(ret, retenciones.Retencion) and ret.origen == "pdf"
    assert ret.id_retenido == PROVEEDOR and ret.periodo_fiscal == "05/2026"
    assert [(l.impuesto, l.codigo, str(l.base), str(l.porcentaje), str(l.valor), l.num_doc_sustento) for l in ret.lineas] == [
        ("1", "312", "100.00", "1.75", "1.75", "001002000000123"), ("2", "1", "15.00", "30.00", "4.50", "001002000000123")]
    assert not ret.avisos_lectura
    doc = _con_compra(esquema)
    res = retenciones.aplicar(doc, retenciones.analizar(doc, [ret]))
    assert res.compras and res.compras[0].texto("valorRetBienes") == "4.50"


def test_pdf_con_numero_e_impuesto_partidos(esquema, tmp_path, monkeypatch):
    from fabrica_comprobantes import texto_ride_retencion_partida

    monkeypatch.setenv("ATSAPP_DATOS", str(tmp_path))
    ret = comprobante_desde_texto_ride(texto_ride_retencion_partida(INFORMANTE, PROVEEDOR))
    assert [(l.impuesto, l.codigo, str(l.base), str(l.porcentaje), str(l.valor), l.num_doc_sustento) for l in ret.lineas] == [
        ("2", "2", "79.37", "70.00", "55.56", "001001000000019"), ("1", "", "529.10", "10.00", "52.91", "001001000000019")]
    assert ret.periodo_fiscal == "07/2026"
    # anexo de julio con la factura 001-001-000000019 del proveedor
    doc = _doc_minimo(esquema)
    doc.raiz.poner("Mes", "07")
    fac = leer_bytes(factura(sec="000000019", fecha="27/07/2026", impuestos=(("2", "4", "529.10", "79.37"),),
                             total="608.47").encode())
    fac.estab, fac.pto_emi = "001", "001"
    props = comprobantes.analizar(doc, [fac])
    comprobantes.importar(doc, props)
    pr = retenciones.analizar(doc, [ret])
    assert pr[0].estado == AVISO and "elíjalo" in pr[0].notas[-1]
    retenciones.lineas_sin_codigo(ret)[0].codigo = "303"  # lo que el usuario elige en la vista previa
    res = retenciones.aplicar(doc, pr)
    c = res.compras[0]
    assert c.texto("valorRetServicios") == "55.56"
    assert [(a.texto("codRetAir"), a.texto("valRetAir")) for a in c.hijo("air").lista("detalleAir")] == [("303", "52.91")]
    retenciones.recordar_codigos(ret)
    # la próxima retención del mismo proveedor sugiere el 303
    otra = comprobante_desde_texto_ride(texto_ride_retencion_partida(INFORMANTE, PROVEEDOR, sec="000000900"))
    doc2 = _doc_minimo(esquema)
    doc2.raiz.poner("Mes", "07")
    comprobantes.importar(doc2, comprobantes.analizar(doc2, [fac]))
    pr2 = retenciones.analizar(doc2, [otra])
    assert retenciones.lineas_sin_codigo(otra)[0].codigo == "303"
    assert "tomado de compras anteriores" in pr2[0].notas[-1]
