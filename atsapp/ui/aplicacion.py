"""Arranque de la interfaz gráfica."""

from __future__ import annotations

import sys

from PySide6.QtCore import QCoreApplication, QLocale
from PySide6.QtWidgets import QApplication, QMessageBox

from .. import rutas
from ..catalogos import Catalogos
from ..esquema import Esquema


def ejecutar(argumentos: list[str]) -> int:
    QCoreApplication.setOrganizationName("atsapp")
    QCoreApplication.setApplicationName("Editor ATS")
    QLocale.setDefault(QLocale(QLocale.Spanish, QLocale.Ecuador))
    app = QApplication([sys.argv[0]] + argumentos)

    from .dialogos import DialogoEsquema
    from .ventana import VentanaPrincipal

    try:
        esquema = Esquema(rutas.ruta_esquema())
        catalogos = Catalogos.cargar()
    except Exception as e:  # noqa: BLE001 - se informa al usuario
        QMessageBox.critical(None, "Error", f"No se pudo cargar el esquema o los catálogos:\n{e}")
        dlg = DialogoEsquema(obligatorio=True)
        if not dlg.exec() or not dlg.importado:
            return 1
        esquema = Esquema(rutas.ruta_esquema())
        catalogos = Catalogos.cargar()

    ventana = VentanaPrincipal(esquema, catalogos)
    ventana.show()
    archivos = [a for a in argumentos if not a.startswith("-")]
    if archivos:
        ventana.abrir(archivos[0])
    return app.exec()
