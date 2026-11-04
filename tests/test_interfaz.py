"""Prueba básica de la interfaz sin pantalla (QT_QPA_PLATFORM=offscreen)."""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")


@pytest.fixture(scope="module")
def app(tmp_path_factory):
    os.environ["XDG_CONFIG_HOME"] = str(tmp_path_factory.mktemp("config"))
    from PySide6.QtCore import QCoreApplication

    QCoreApplication.setOrganizationName("atsapp-pruebas")
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_ventana_abre_anexo(app, esquema, catalogos, anexo_real):
    from atsapp.ui.ventana import VentanaPrincipal

    v = VentanaPrincipal(esquema, catalogos)
    v.abrir(str(anexo_real))
    assert v.pestanas.count() > 3
    assert len(v.paneles["compras"].modelo.filas()) == 60
    assert not [m for m in v.mensajes if m.es_error]
    assert v.doc.a_bytes() == anexo_real.read_bytes()
    v.modificado = False
    v.close()


def test_editor_marca_errores(app, esquema, catalogos, anexo_real):
    from atsapp.ui.editor import DialogoRegistro
    from atsapp.ui.ventana import VentanaPrincipal

    v = VentanaPrincipal(esquema, catalogos)
    v.abrir(str(anexo_real))
    panel = v.paneles["compras"]
    original = panel.modelo.filas()[0]
    copia = original.copiar()
    copia.poner("fechaRegistro", "01/01/2020")
    d = DialogoRegistro(copia, catalogos, panel.periodo, "Compra 1", v, original=original,
                        contenedor=panel.contenedor, validador=panel.validador)
    mensajes = d.verificar()
    assert any(m.ruta.endswith("fechaRegistro") for m in mensajes)
    assert d.formulario.celdas["fechaRegistro"].error.text()
    d.reject()
    # el documento no cambió por validar el registro
    assert v.doc.a_bytes() == anexo_real.read_bytes()
    v.modificado = False
    v.close()


def test_normalizaciones():
    from atsapp.ui.campos import normalizar_fecha, normalizar_numero

    assert normalizar_numero("1.234,5", 2) == "1234.50"
    assert normalizar_numero("1,234.5", 2) == "1234.50"
    assert normalizar_numero("12", 2) == "12.00"
    assert normalizar_numero("abc", 2) == "abc"
    assert normalizar_fecha("7/5/2026") == "07/05/2026"
    assert normalizar_fecha("07052026") == "07/05/2026"


def test_dialogo_importar_comprobantes(app, esquema, catalogos, tmp_path, monkeypatch):
    monkeypatch.setenv("ATSAPP_DATOS", str(tmp_path / "datos"))
    from fabrica_comprobantes import factura, retencion, sobre
    from test_nucleo import _doc_minimo

    from atsapp import comprobantes
    from atsapp.ui.importar_comprobantes import C_SEL, DialogoImportarComprobantes
    from atsapp.ui.ventana import VentanaPrincipal

    (tmp_path / "a.xml").write_text(sobre(factura(sec="1")), encoding="utf-8")
    (tmp_path / "b.xml").write_text(retencion(), encoding="utf-8")
    v = VentanaPrincipal(esquema, catalogos)
    v.poner_documento(_doc_minimo(esquema), None)
    leidos = comprobantes.leer_rutas([tmp_path / "a.xml", tmp_path / "b.xml"])
    dlg = DialogoImportarComprobantes(v.doc, leidos, catalogos, v._periodo(), v)
    assert dlg.tabla.rowCount() == 2
    assert sum(p.seleccionado for p in dlg.propuestas) == 1
    from PySide6.QtCore import Qt

    dlg.tabla.item(0, C_SEL).setCheckState(Qt.Unchecked)
    assert not dlg.propuestas[0].seleccionado
    dlg.reject()
    v.modificado = False
    v.close()


def test_diagnostico_ruc_distinto(app, esquema, catalogos, tmp_path):
    from fabrica_comprobantes import INFORMANTE, factura
    from test_nucleo import _doc_minimo

    from atsapp import comprobantes
    from atsapp.ui.importar_comprobantes import DialogoImportarComprobantes

    doc = _doc_minimo(esquema)
    doc.raiz.poner("IdInformante", "1700000000001")
    leidos = [comprobantes.leer_bytes(factura(sec=str(i)).encode(), f"{i}.xml") for i in range(3)]
    dlg = DialogoImportarComprobantes(doc, leidos, catalogos, (None, None))
    assert f"cree el anexo con el RUC {INFORMANTE}" in dlg.resumen.text()
    dlg.reject()
    doc.raiz.poner("IdInformante", INFORMANTE)
    doc.raiz.poner("Mes", "10")
    dlg = DialogoImportarComprobantes(doc, leidos, catalogos, (None, None))
    assert "05/2026" in dlg.resumen.text()
    dlg.reject()
