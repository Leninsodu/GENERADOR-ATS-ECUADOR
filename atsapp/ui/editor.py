"""Ventana de edición de un registro (una compra, una venta, una retención...)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QByteArray, QSettings, QTimer, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QFrame, QLabel, QMessageBox, QScrollArea,
                               QVBoxLayout)

from ..catalogos import Catalogos
from ..documento import Nodo
from ..presentacion import describir_ruta
from ..validacion import Mensaje, validar_nodo
from .formulario import FormularioNodo


class DialogoRegistro(QDialog):
    def __init__(self, nodo: Nodo, catalogos: Catalogos | None, periodo, titulo: str, parent=None,
                 original: Nodo | None = None, contenedor: Nodo | None = None,
                 validador: Callable[[Nodo | None, Nodo], tuple[list[Mensaje], str]] | None = None,
                 enfocar: str | None = None):
        super().__init__(parent)
        self.nodo = nodo
        self.catalogos = catalogos
        self.periodo = periodo
        self.original = original
        self.contenedor = contenedor
        self.validador = validador
        self.setWindowTitle(titulo)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setSizeGripEnabled(True)

        self.formulario = FormularioNodo(nodo, catalogos, periodo)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setWidget(self.formulario)

        self.resumen = QLabel()
        self.resumen.setWordWrap(True)
        self.resumen.setTextFormat(Qt.RichText)
        self.resumen.setStyleSheet("QLabel { background: rgba(198,40,40,0.08); border: 1px solid rgba(198,40,40,0.4);"
                                   " border-radius: 4px; padding: 6px; }")
        self.resumen.hide()

        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText("Aceptar")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        self.b_verificar = botones.addButton("Verificar", QDialogButtonBox.ActionRole)
        self.b_verificar.clicked.connect(self.verificar)
        botones.accepted.connect(self.aceptar)
        botones.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(self.resumen)
        lay.addWidget(area, 1)
        lay.addWidget(botones)
        self._clave_geometria = f"dialogo/{nodo.nombre}"
        self._restaurar_geometria()
        if enfocar:
            QTimer.singleShot(0, lambda: (self.verificar(), self.formulario.enfocar(enfocar)))

    # --- tamaño adaptado a la pantalla ----------------------------------------------
    def _restaurar_geometria(self) -> None:
        guardada = QSettings().value(self._clave_geometria)
        if isinstance(guardada, QByteArray) and self.restoreGeometry(guardada):
            return
        pantalla = (self.parent().screen() if self.parent() else None) or QGuiApplication.primaryScreen()
        disp = pantalla.availableGeometry()
        ancho = min(int(disp.width() * 0.85), 1200)
        alto = min(int(disp.height() * 0.85), 900)
        self.resize(ancho, alto)

    def done(self, resultado: int) -> None:
        QSettings().setValue(self._clave_geometria, self.saveGeometry())
        super().done(resultado)

    # --- validación ---------------------------------------------------------------------
    def _mensajes(self) -> tuple[list[Mensaje], str]:
        if self.validador is not None:
            return self.validador(self.original, self.nodo)
        return validar_nodo(self.nodo, self.catalogos, self.periodo), self.nodo.ruta()

    def verificar(self) -> list[Mensaje]:
        mensajes, base = self._mensajes()
        self.formulario.limpiar_errores()
        sobrantes = self.formulario.mostrar_mensajes(mensajes, base)
        errores = [m for m in mensajes if m.es_error]
        avisos = [m for m in mensajes if not m.es_error]
        if not mensajes:
            self.resumen.setText("✔ Sin problemas.")
            self.resumen.setStyleSheet("QLabel { background: rgba(46,125,50,0.10); border: 1px solid rgba(46,125,50,0.4);"
                                       " border-radius: 4px; padding: 6px; }")
            self.resumen.show()
            return mensajes
        self.resumen.setStyleSheet("QLabel { background: rgba(198,40,40,0.08); border: 1px solid rgba(198,40,40,0.4);"
                                   " border-radius: 4px; padding: 6px; }")
        lineas = [f"<b>{len(errores)} error(es), {len(avisos)} advertencia(s).</b> Los campos con problema están marcados en rojo."]
        for m in sobrantes[:6]:
            lineas.append(f"• {m.severidad.texto}: {describir_ruta(m.ruta)} — {m.texto}")
        if len(sobrantes) > 6:
            lineas.append(f"… y {len(sobrantes) - 6} más")
        self.resumen.setText("<br>".join(lineas))
        self.resumen.show()
        return mensajes

    def aceptar(self) -> None:
        mensajes = self.verificar()
        errores = [m for m in mensajes if m.es_error]
        if errores:
            r = QMessageBox.question(
                self, "Registro con errores",
                f"El registro tiene {len(errores)} error(es). Puede guardarlo ahora y corregirlo después, "
                "pero el anexo no se podrá exportar sin corregirlos.\n\n¿Guardar de todos modos?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        self.accept()

