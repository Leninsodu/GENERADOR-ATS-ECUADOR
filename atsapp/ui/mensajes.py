"""Panel inferior con los errores y advertencias del anexo."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QHBoxLayout, QHeaderView, QLabel,
                               QStyle, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..presentacion import describir_ruta
from ..validacion import Mensaje, Severidad


class PanelMensajes(QWidget):
    activado = Signal(object)  # Mensaje

    def __init__(self, parent=None):
        super().__init__(parent)
        self._mensajes: list[Mensaje] = []
        self.filtro = QComboBox()
        self.filtro.addItems(["Todos", "Solo errores", "Solo advertencias"])
        self.filtro.currentIndexChanged.connect(lambda _i: self._llenar())
        self.resumen = QLabel()
        arriba = QHBoxLayout()
        arriba.addWidget(self.resumen, 1)
        arriba.addWidget(QLabel("Mostrar:"))
        arriba.addWidget(self.filtro)

        self.tabla = QTableWidget(0, 3)
        self.tabla.setHorizontalHeaderLabels(["Tipo", "Ubicación", "Detalle"])
        self.tabla.verticalHeader().hide()
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabla.setWordWrap(False)
        cab = self.tabla.horizontalHeader()
        cab.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        cab.setSectionResizeMode(1, QHeaderView.Interactive)
        cab.setStretchLastSection(True)
        self.tabla.setColumnWidth(1, 320)
        self.tabla.cellDoubleClicked.connect(self._activar)
        self.tabla.setToolTip("Doble clic para ir al campo")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addLayout(arriba)
        lay.addWidget(self.tabla, 1)
        self.poner([])

    def poner(self, mensajes: list[Mensaje]) -> None:
        self._mensajes = mensajes
        errores = sum(1 for m in mensajes if m.es_error)
        avisos = len(mensajes) - errores
        if not mensajes:
            self.resumen.setText("✔ El anexo no tiene errores ni advertencias.")
        else:
            self.resumen.setText(f"{errores} error(es) · {avisos} advertencia(s). Doble clic en una fila para ir al campo.")
        self._llenar()

    def _visibles(self) -> list[Mensaje]:
        f = self.filtro.currentIndex()
        if f == 1:
            return [m for m in self._mensajes if m.es_error]
        if f == 2:
            return [m for m in self._mensajes if not m.es_error]
        return self._mensajes

    def _llenar(self) -> None:
        visibles = self._visibles()
        self.tabla.setRowCount(len(visibles))
        estilo = QApplication.style()
        icono_error = estilo.standardIcon(QStyle.SP_MessageBoxCritical)
        icono_aviso = estilo.standardIcon(QStyle.SP_MessageBoxWarning)
        for i, m in enumerate(visibles):
            tipo = QTableWidgetItem(icono_error if m.severidad is Severidad.ERROR else icono_aviso, m.severidad.texto)
            tipo.setData(Qt.UserRole, i)
            ubic = QTableWidgetItem(describir_ruta(m.ruta))
            ubic.setToolTip(m.ruta)
            det = QTableWidgetItem(m.texto)
            det.setToolTip(m.texto)
            for c, item in enumerate((tipo, ubic, det)):
                self.tabla.setItem(i, c, item)

    def _activar(self, fila: int, _col: int) -> None:
        visibles = self._visibles()
        if 0 <= fila < len(visibles):
            self.activado.emit(visibles[fila])
