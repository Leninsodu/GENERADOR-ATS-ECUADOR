import zipfile

from fabrica_comprobantes import CLIENTE, INFORMANTE, PROVEEDOR, clave_acceso, factura, liquidacion, nota_credito, retencion, sobre

from atsapp.comprobantes import (AVISO, OK, OMITIR, ArchivoNoLeido, analizar, importar, leer_bytes, leer_rutas,
                                 parece_anexo)
from atsapp.validacion import validar_documento, validar_xsd
from test_nucleo import _cedula, _doc_minimo


def _escribir(tmp_path, nombre, contenido):
    p = tmp_path / nombre
    p.write_text(contenido, encoding="utf-8")
    return p


def test_lee_sobre_de_autorizacion():
    c = leer_bytes(sobre(factura()).encode(), "f.xml")
    assert c.tipo == "01" and c.ruc_emisor == PROVEEDOR and c.id_contraparte == INFORMANTE
    assert c.numero == "001-002-000000123"
    assert c.estado == "AUTORIZADO"
    assert c.autorizacion == clave_acceso(fecha="10052026", ruc=PROVEEDOR, serie="001002", sec="000000123")
    assert str(c.base_gravada) == "100.00" and str(c.base_cero) == "20.00" and str(c.iva) == "15.00"
    assert c.formas_pago == ["20"]


def test_lee_xml_suelto_firmado():
    c = leer_bytes(factura(firma=True).encode(), "f.xml")
    assert c.estado == "" and len(c.autorizacion) == 49


def test_rechaza_retencion_y_anexo():
    for datos in (retencion(), "<iva><Anio>2026</Anio></iva>", "no es xml"):
        try:
            leer_bytes(datos.encode())
        except Exception as e:  # noqa: BLE001
            assert type(e).__name__ == "ErrorComprobante"
        else:
            raise AssertionError("debió rechazarse")


def test_zip_y_carpeta(tmp_path):
    z = tmp_path / "descarga.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("a.xml", sobre(factura(sec="000000001")))
        zf.writestr("b.xml", retencion())
    carpeta = tmp_path / "otros"
    carpeta.mkdir()
    _escribir(carpeta, "c.xml", factura(sec="000000002"))
    leidos = leer_rutas([z, carpeta])
    assert sum(1 for x in leidos if not isinstance(x, ArchivoNoLeido)) == 2
    assert sum(1 for x in leidos if isinstance(x, ArchivoNoLeido)) == 1


def test_importa_factura_valida(esquema, catalogos):
    doc = _doc_minimo(esquema)
    comps = [leer_bytes(sobre(factura()).encode(), "f.xml")]
    props = analizar(doc, comps)
    assert props[0].estado == OK and props[0].seleccionado
    creados = importar(doc, props)
    assert len(creados) == 1
    c = creados[0]
    assert c.texto("idProv") == PROVEEDOR and c.texto("fechaRegistro") == "10/05/2026"
    assert c.texto("baseImpGrav") == "100.00" and c.texto("montoIva") == "15.00"
    assert c.hijo("formasDePago") is None  # menos de USD 500: no se informa
    assert validar_xsd(doc) == []
    assert [m.texto for m in validar_documento(doc, catalogos) if m.es_error] == []


def test_forma_de_pago_sobre_500(esquema, catalogos):
    doc = _doc_minimo(esquema)
    comps = [leer_bytes(factura(impuestos=(("2", "4", "600.00", "90.00"),), pagos=("19", "20"), total="690.00").encode())]
    importar(doc, analizar(doc, comps))
    c = doc.raiz.hijo("compras").lista("detalleCompras")[0]
    assert [h.valor for h in c.hijo("formasDePago").lista("formaPago")] == ["19", "20"]
    assert [m for m in validar_documento(doc, catalogos) if m.es_error] == []


def test_estados_omitidos(esquema):
    doc = _doc_minimo(esquema)
    comps = [
        leer_bytes(factura(comprador="1790010937001", sec="1").encode()),  # a otro comprador
        leer_bytes(factura(fecha="02/06/2026", sec="2").encode()),  # período posterior
        leer_bytes(factura(ambiente="1", sec="3").encode()),  # pruebas
        leer_bytes(sobre(factura(sec="4"), estado="NO AUTORIZADO").encode()),
    ]
    props = analizar(doc, comps)
    assert all(p.estado == OMITIR and not p.seleccionado for p in props)


def test_periodo_anterior_y_duplicados(esquema):
    doc = _doc_minimo(esquema)
    anterior = leer_bytes(factura(fecha="28/04/2026", sec="9").encode())
    props = analizar(doc, [anterior, anterior])
    assert props[0].estado == AVISO and props[0].fecha_registro.isoformat() == "2026-05-01"
    assert props[1].estado == OMITIR  # repetido en el lote
    importar(doc, props)
    assert analizar(doc, [anterior])[0].estado == OMITIR  # ya existe en el anexo


def test_nota_credito_toma_autorizacion_de_la_factura(esquema, catalogos):
    doc = _doc_minimo(esquema)
    fac = leer_bytes(sobre(factura()).encode())
    nc = leer_bytes(nota_credito().encode())
    props = analizar(doc, [fac, nc])
    importar(doc, props)
    compras = doc.raiz.hijo("compras").lista("detalleCompras")
    assert compras[1].texto("tipoComprobante") == "04"
    assert compras[1].texto("autModificado") == fac.autorizacion
    assert compras[1].texto("secModificado") == "000000123"
    assert validar_xsd(doc) == []


def test_liquidacion_de_compra(esquema, catalogos):
    doc = _doc_minimo(esquema)
    ced = _cedula("171234567")
    props = analizar(doc, [leer_bytes(liquidacion(ced).encode())])
    assert props[0].estado == OK
    importar(doc, props)
    c = doc.raiz.hijo("compras").lista("detalleCompras")[0]
    assert (c.texto("tpIdProv"), c.texto("idProv"), c.texto("tipoComprobante")) == ("02", ced, "03")
    assert validar_xsd(doc) == []


def test_sustento_de_compras_anteriores(esquema):
    doc = _doc_minimo(esquema)
    importar(doc, analizar(doc, [leer_bytes(factura(sec="1").encode())], sustento_defecto="02"))
    props = analizar(doc, [leer_bytes(factura(sec="2").encode())], sustento_defecto="01")
    assert props[0].sustento == "02"  # se reutiliza el del mismo proveedor


def test_parece_anexo(tmp_path, anexo_real):
    assert parece_anexo(anexo_real)
    assert not parece_anexo(_escribir(tmp_path, "f.xml", factura()))


def test_marca_ya_registrado(esquema):
    doc = _doc_minimo(esquema)
    f = leer_bytes(factura(sec="7").encode())
    importar(doc, analizar(doc, [f]))
    p = analizar(doc, [f])[0]
    assert p.estado == OMITIR and p.ya_registrado


# --- ventas desde el PDF (RIDE) -------------------------------------------------------------
import os
from pathlib import Path

import pytest

from atsapp.comprobantes import comprobante_desde_texto_ride
from fabrica_comprobantes import texto_ride


def test_lee_texto_ride():
    c = comprobante_desde_texto_ride(texto_ride(), "f.pdf")
    assert (c.tipo, c.numero, c.ruc_emisor) == ("01", "001-002-000000466", INFORMANTE)
    assert c.fecha_emision.isoformat() == "2026-05-05"
    assert (c.tipo_id_contraparte, c.id_contraparte) == ("04", CLIENTE)
    assert c.razon_contraparte == "CLIENTE DE PRUEBA S.A."
    assert (str(c.base_gravada), str(c.base_cero), str(c.iva), str(c.total)) == ("900.00", "90.00", "135.00", "1125.00")
    assert c.formas_pago == ["20"] and c.cuadra


def test_ride_que_no_cuadra():
    c = comprobante_desde_texto_ride(texto_ride(total="1200.00"))
    assert not c.cuadra


def test_ventas_se_agrupan_por_cliente(esquema, catalogos):
    doc = _doc_minimo(esquema)
    comps = [comprobante_desde_texto_ride(texto_ride(sec="000000001")),
             comprobante_desde_texto_ride(texto_ride(sec="000000002", grav="100.00", cero="0.00", iva="15.00", total="115.00")),
             comprobante_desde_texto_ride(texto_ride(cliente=_cedula("091234567"), nombre="PERSONA", sec="000000003", grav="0.00",
                                                     cero="50.00", iva="0.00", total="50.00"))]
    props = analizar(doc, comps)
    assert [p.destino for p in props] == ["ventas"] * 3 and all(p.estado == OK for p in props)
    res = importar(doc, props)
    ventas = doc.raiz.hijo("ventas").lista("detalleVentas")
    assert len(ventas) == 2 and len(res.claves_ventas) == 3
    v = ventas[0]
    assert (v.texto("tipoComprobante"), v.texto("tipoEmision"), v.texto("numeroComprobantes")) == ("18", "F", "2")
    assert (v.texto("baseImpGrav"), v.texto("baseImponible"), v.texto("montoIva")) == ("1000.00", "90.00", "150.00")
    assert ventas[1].texto("tpIdCliente") == "05"
    assert doc.raiz.texto("totalVentas") == "1140.00"
    est = doc.raiz.hijo("ventasEstablecimiento").lista("ventaEst")
    assert [(e.texto("codEstab"), e.texto("ventasEstab")) for e in est] == [("001", "1140.00")]
    assert validar_xsd(doc) == []
    assert [m.texto for m in validar_documento(doc, catalogos) if m.es_error] == []
    # volver a importar las mismas: se reconocen por la clave de acceso
    props2 = analizar(doc, comps, ventas_importadas=set(res.claves_ventas))
    assert all(p.ya_registrado and not p.seleccionado for p in props2)


def test_venta_fuera_de_periodo(esquema):
    doc = _doc_minimo(esquema)
    p = analizar(doc, [comprobante_desde_texto_ride(texto_ride(fecha="05062026"))])[0]
    assert p.estado == OMITIR


PDF_REALES = Path(os.environ.get("ATSAPP_PDF_VENTAS", "/no-configurado"))


@pytest.mark.skipif(not PDF_REALES.is_dir(), reason="no hay PDF de ventas reales")
def test_pdf_reales_coinciden_con_anexo(esquema, anexo_real):
    from atsapp.documento import Documento

    real = Documento.desde_archivo(esquema, anexo_real)
    leidos = [c for c in leer_rutas([PDF_REALES]) if not isinstance(c, ArchivoNoLeido)]
    assert leidos and all(c.cuadra for c in leidos)
    nuevo = _doc_minimo(esquema)
    nuevo.raiz.poner("IdInformante", real.raiz.texto("IdInformante"))
    importar(nuevo, analizar(nuevo, leidos))
    assert nuevo.raiz.texto("totalVentas") == real.raiz.texto("totalVentas")



def test_registro_no_aplica_a_anexo_nuevo(esquema):
    """Si se guardó otro anexo del mismo mes, un anexo nuevo vacío debe poder importar las mismas ventas."""
    comps = [comprobante_desde_texto_ride(texto_ride(sec="000000001"))]
    nuevo = _doc_minimo(esquema)
    p = analizar(nuevo, comps, ventas_importadas={comps[0].clave_acceso})[0]
    assert p.estado == OK and p.seleccionado and not p.ya_registrado
