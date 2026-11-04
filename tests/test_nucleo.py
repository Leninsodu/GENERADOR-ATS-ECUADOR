import re
import zipfile

import pytest
from fabrica_comprobantes import INFORMANTE

from atsapp.documento import Documento, crear_vacio
from atsapp.identificacion import cedula_valida, ruc_valido
from atsapp.reglas import aplicar_reglas
from atsapp.validacion import validar_documento, validar_xsd


def _cedula(base9: str) -> str:
    suma = 0
    for i, c in enumerate(base9):
        n = int(c) * (2 if i % 2 == 0 else 1)
        suma += n - 9 if n > 9 else n
    return base9 + str((10 - suma % 10) % 10)


def _ruc_sociedad(base9: str) -> str:
    coef = [4, 3, 2, 7, 6, 5, 4, 3, 2]
    r = sum(int(d) * c for d, c in zip(base9, coef)) % 11
    return base9 + str(0 if r == 0 else 11 - r) + "001"


# --- esquema -------------------------------------------------------------------------
def test_esquema_estructura(esquema):
    raiz = esquema.raiz
    assert raiz.nombre == "iva"
    nombres = [h.nombre for h in raiz.hijos]
    assert nombres[:5] == ["TipoIDInformante", "IdInformante", "razonSocial", "Anio", "Mes"]
    compra = raiz.buscar("detalleCompras")
    assert compra.es_repetible and not compra.es_simple
    assert [h.nombre for h in compra.hijos][:3] == ["codSustento", "tpIdProv", "idProv"]
    assert raiz.hijo("IdInformante").tipo.errores(INFORMANTE) == []
    assert raiz.hijo("IdInformante").tipo.errores("17919122920") != []


def test_patrones_compilan(esquema):
    for d in _todos(esquema.raiz):
        if d.tipo:
            for grupo in d.tipo.patrones:
                for p in grupo:
                    re.compile(p)


def _todos(d):
    yield d
    for h in d.hijos:
        yield from _todos(h)


def test_monto_formato(esquema):
    tipo = esquema.raiz.buscar("baseImpGrav").tipo
    assert tipo.errores("73.48") == []
    assert tipo.errores("73,48") != []
    assert tipo.errores("1.234") != []


# --- documento ---------------------------------------------------------------------
def test_ida_y_vuelta_identica(esquema, anexo_real):
    original = anexo_real.read_bytes()
    doc = Documento.desde_archivo(esquema, anexo_real)
    assert doc.a_bytes() == original


def test_anexo_real_valido(esquema, catalogos, anexo_real):
    doc = Documento.desde_archivo(esquema, anexo_real)
    assert validar_xsd(doc) == []
    mensajes = validar_documento(doc, catalogos)
    assert [m for m in mensajes if m.es_error] == []


def test_agregar_respeta_orden(esquema):
    doc = Documento(esquema)
    raiz = doc.raiz
    raiz.poner("codigoOperativo", "IVA")
    raiz.poner("razonSocial", "EMPRESA PRUEBA")
    raiz.poner("IdInformante", INFORMANTE)
    orden = [h.nombre for h in raiz.hijos]
    assert orden.index("IdInformante") < orden.index("razonSocial") < orden.index("codigoOperativo")


def test_opcionales_vacios_no_se_escriben(esquema):
    doc = _doc_minimo(esquema)
    xml = doc.a_bytes().decode()
    assert "<regimenMicroempresa" not in xml
    assert "<exportaciones" not in xml
    assert xml.startswith('<?xml version="1.0" encoding="UTF-8" standalone="no"?><iva>')


def test_zip_para_sri(esquema, tmp_path):
    doc = _doc_minimo(esquema)
    destino = tmp_path / doc.nombre_sugerido(".zip")
    doc.guardar_zip(destino)
    assert destino.name == "AT052026.zip"
    with zipfile.ZipFile(destino) as z:
        assert z.namelist() == ["AT-052026.xml"]
        assert z.read("AT-052026.xml") == doc.a_bytes()
    reabierto = Documento.desde_archivo(esquema, destino)
    assert reabierto.a_bytes() == doc.a_bytes()


def test_rechaza_xml_ajeno(esquema):
    with pytest.raises(ValueError):
        Documento.desde_bytes(esquema, b"<factura/>")


def test_entidades_externas_no_se_resuelven(esquema):
    xml = b'<?xml version="1.0"?><!DOCTYPE iva [<!ENTITY x SYSTEM "file:///etc/passwd">]><iva><razonSocial>&x;</razonSocial></iva>'
    doc = Documento.desde_bytes(esquema, xml)
    assert "root" not in doc.raiz.texto("razonSocial")


# --- reglas ------------------------------------------------------------------------
def _doc_minimo(esquema):
    doc = Documento(esquema)
    r = doc.raiz
    for campo, valor in (("TipoIDInformante", "R"), ("IdInformante", INFORMANTE), ("razonSocial", "EMPRESA PRUEBA"),
                         ("Anio", "2026"), ("Mes", "05"), ("numEstabRuc", "001"), ("totalVentas", "0.00"),
                         ("codigoOperativo", "IVA")):
        r.poner(campo, valor)
    return doc


def _compra(doc, **valores):
    compras = doc.raiz.hijo("compras") or doc.raiz.agregar("compras")
    c = compras.agregar("detalleCompras", crear_vacio(doc.esquema.raiz.buscar("detalleCompras")))
    base = dict(codSustento="01", tpIdProv="01", idProv=_ruc_sociedad("179191229"), tipoComprobante="01", parteRel="NO",
                fechaRegistro="10/05/2026", establecimiento="001", puntoEmision="001", secuencial="123",
                fechaEmision="10/05/2026", autorizacion="1234567890", baseNoGraIva="0.00", baseImponible="0.00",
                baseImpGrav="100.00", baseImpExe="0.00", montoIce="0.00", montoIva="15.00", valRetBien10="0.00",
                valRetServ20="0.00", valorRetBienes="0.00", valRetServ50="0.00", valorRetServicios="0.00",
                valRetServ100="0.00")
    base.update(valores)
    for k, v in base.items():
        c.poner(k, v)
    pe = c.hijo("pagoExterior") or c.agregar("pagoExterior")
    for k, v in dict(pagoLocExt="01", paisEfecPago="NA", aplicConvDobTrib="NA", pagExtSujRetNorLeg="NA").items():
        pe.poner(k, v)
    return c


def _textos(doc, catalogos):
    return [m.texto for m in aplicar_reglas(doc, catalogos) if m.es_error]


def test_compra_correcta_sin_errores(esquema, catalogos):
    doc = _doc_minimo(esquema)
    _compra(doc)
    assert validar_xsd(doc) == []
    assert [m for m in validar_documento(doc, catalogos) if m.es_error] == []


def test_fecha_fuera_de_periodo(esquema, catalogos):
    doc = _doc_minimo(esquema)
    _compra(doc, fechaRegistro="10/04/2026", fechaEmision="10/04/2026")
    assert any("dentro del período" in t for t in _textos(doc, catalogos))


def test_emision_posterior_al_registro(esquema, catalogos):
    doc = _doc_minimo(esquema)
    _compra(doc, fechaRegistro="05/05/2026", fechaEmision="06/05/2026")
    assert any("mayor o igual a la fecha de emisión" in t for t in _textos(doc, catalogos))


def test_forma_de_pago_obligatoria_sobre_500(esquema, catalogos):
    doc = _doc_minimo(esquema)
    _compra(doc, baseImpGrav="500.00", montoIva="75.00")
    assert any("forma de pago" in t for t in _textos(doc, catalogos))
    doc2 = _doc_minimo(esquema)
    _compra(doc2, baseImpGrav="400.00", montoIva="60.00")
    assert not any("forma de pago" in t for t in _textos(doc2, catalogos))


def test_sustento_no_valido_para_comprobante(esquema, catalogos):
    doc = _doc_minimo(esquema)
    _compra(doc, tipoComprobante="02", codSustento="01")  # nota de venta no da crédito tributario
    assert any("sustento 01 no es válido" in t for t in _textos(doc, catalogos))


def test_duplicados(esquema, catalogos):
    doc = _doc_minimo(esquema)
    _compra(doc)
    _compra(doc)
    assert any("duplicado" in t for t in _textos(doc, catalogos))


def test_cedula_invalida(esquema, catalogos):
    doc = _doc_minimo(esquema)
    mala = _cedula("171234567")[:-1] + "0" if not _cedula("171234567").endswith("0") else _cedula("171234567")[:-1] + "1"
    _compra(doc, tpIdProv="02", idProv=mala)
    assert any("no es válida" in t for t in _textos(doc, catalogos))


def test_total_ventas(esquema, catalogos):
    doc = _doc_minimo(esquema)
    ventas = doc.raiz.agregar("ventas")
    v = ventas.agregar("detalleVentas", crear_vacio(esquema.raiz.buscar("detalleVentas")))
    for k, val in dict(tpIdCliente="04", idCliente=_ruc_sociedad("179191229"), parteRelVtas="NO", tipoComprobante="18",
                       tipoEmision="F", numeroComprobantes="1", baseNoGraIva="0.00", baseImponible="0.00",
                       baseImpGrav="100.00", montoIva="15.00", montoIce="0.00", valorRetIva="0.00",
                       valorRetRenta="0.00").items():
        v.poner(k, val)
    fp = v.hijo("formasDePago") or v.agregar("formasDePago")
    (fp.hijo("formaPago") or fp.agregar("formaPago")).valor = "20"
    assert any("total de ventas" in t for t in _textos(doc, catalogos))
    doc.raiz.poner("totalVentas", "100.00")
    assert not any("total de ventas" in t for t in _textos(doc, catalogos))


# --- identificación ---------------------------------------------------------------
def test_identificaciones():
    assert cedula_valida(_cedula("171234567"))
    assert cedula_valida(_cedula("176000001"))  # tercer dígito 6 (cédulas nuevas)
    assert not cedula_valida("1712345670" if not cedula_valida("1712345670") else "1712345671")
    assert ruc_valido(_ruc_sociedad("179191229"))
    assert ruc_valido(_cedula("171234567") + "001")
    assert not ruc_valido(INFORMANTE[:9] + str((int(INFORMANTE[9]) + 1) % 10) + "001")


def test_clave_de_acceso(esquema, anexo_real):
    from atsapp.identificacion import clave_acceso_valida, ruc_en_clave_acceso

    doc = Documento.desde_archivo(esquema, anexo_real)
    claves = [c.texto("autorizacion") for c in doc.raiz.hijo("compras").lista("detalleCompras")]
    largas = [c for c in claves if len(c) == 49]
    assert largas and all(clave_acceso_valida(c) for c in largas)
    c = largas[0]
    assert not clave_acceso_valida(c[:-1] + str((int(c[-1]) + 1) % 10))
    assert len(ruc_en_clave_acceso(c)) == 13



def test_importar_esquema_desde_plugin(plugin_ats, ruta_xsd, tmp_path):
    from atsapp import importador

    destino = tmp_path / "at.xsd"
    importador.importar_esquema(plugin_ats, destino)
    assert destino.read_bytes() == ruta_xsd.read_bytes()


def test_total_como_dimm_ignora_ventas_electronicas(esquema, catalogos):
    """Reproduce el error de DIMM: con ventas E la suma de ventas es 0.00."""
    from atsapp.reglas import total_ventas

    doc = _doc_minimo(esquema)
    ventas = doc.raiz.agregar("ventas")
    v = ventas.agregar("detalleVentas", crear_vacio(esquema.raiz.buscar("detalleVentas")))
    for k, val in dict(tpIdCliente="04", idCliente=_ruc_sociedad("179191229"), parteRelVtas="NO", tipoComprobante="18",
                       tipoEmision="E", numeroComprobantes="1", baseNoGraIva="0.00", baseImponible="0.00",
                       baseImpGrav="100.00", montoIva="15.00", valorRetIva="0.00", valorRetRenta="0.00").items():
        v.poner(k, val)
    (v.agregar("formasDePago").hijo("formaPago")).valor = "20"
    doc.raiz.poner("totalVentas", "100.00")
    assert total_ventas(doc.raiz) == 0
    errores = [m.texto for m in aplicar_reglas(doc, catalogos) if m.es_error]
    assert any("emisión electrónica (E) no se suman" in t for t in errores)
    v.poner("tipoEmision", "F")
    assert total_ventas(doc.raiz) == 100
