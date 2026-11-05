"""Exportación del anexo a Excel (datos sintéticos)."""

from fabrica_comprobantes import INFORMANTE
from openpyxl import load_workbook

from atsapp.documento import Documento
from atsapp.excel import exportar_xlsx


def _doc(esquema) -> Documento:
    doc = Documento(esquema)
    r = doc.raiz
    for campo, valor in (("TipoIDInformante", "R"), ("IdInformante", INFORMANTE), ("razonSocial", "EMPRESA PRUEBA"),
                         ("Anio", "2026"), ("Mes", "05"), ("numEstabRuc", "001"), ("totalVentas", "300.00"),
                         ("codigoOperativo", "IVA")):
        r.poner(campo, valor)
    compras = r.hijo("compras") or r.agregar("compras")
    for sec, base in (("000000001", "100.00"), ("000000002", "50.00")):
        c = compras.agregar("detalleCompras")
        for campo, valor in (("tipoComprobante", "01"), ("idProv", "1799999907001"), ("denoProv", "PROVEEDOR"),
                             ("secuencial", sec), ("baseImpGrav", base), ("montoIva", "15.00"),
                             ("valorRetBienes", "4.50")):
            c.poner(campo, valor)
        air = c.hijo("air") or c.agregar("air")
        d = air.agregar("detalleAir")
        d.poner("codRetAir", "312")
        d.poner("baseImpAir", base)
        d.poner("valRetAir", "1.75")
    ventas = r.hijo("ventas") or r.agregar("ventas")
    v = ventas.agregar("detalleVentas")
    for campo, valor in (("idCliente", "1799999915001"), ("tipoComprobante", "18"), ("numeroComprobantes", "3"),
                         ("baseImpGrav", "300.00"), ("montoIva", "45.00")):
        v.poner(campo, valor)
    return doc


def test_excel_con_resumen_y_tablas(esquema, catalogos, tmp_path):
    ruta = exportar_xlsx(_doc(esquema), tmp_path / "AT-052026.xlsx", catalogos)
    libro = load_workbook(ruta)
    assert libro.sheetnames[:2] == ["Resumen", "Informante"]
    assert {"Compras", "Compras - Ret. renta", "Ventas"} <= set(libro.sheetnames)

    compras = list(libro["Compras"].values)
    assert len(compras) == 3 and compras[1][0] == 1
    col = compras[0].index("Base imponible gravada") if "Base imponible gravada" in compras[0] else None
    assert col is None or compras[1][col] == 100.0

    ret = list(libro["Compras - Ret. renta"].values)
    assert [f[0] for f in ret[1:]] == [1, 2]  # cada retención apunta a su compra

    textos = [c for fila in libro["Resumen"].values for c in fila if c is not None]
    assert "Compras por tipo de comprobante" in textos
    assert 3.5 in textos  # total retenido en la fuente
    assert 150.0 in textos  # total base gravada de compras
