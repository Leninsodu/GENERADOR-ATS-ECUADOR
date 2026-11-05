"""Diálogos auxiliares: nuevo anexo e importación del esquema."""

from __future__ import annotations

import datetime as dt

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox, QVBoxLayout)

from .. import importador
from ..identificacion import ruc_aceptado

def limpiar_texto(texto: str) -> str:
    """El esquema solo admite letras sin tilde, números y espacios: 'Peña & Cía.' -> 'PENA CIA'."""
    import re
    import unicodedata

    sin_tildes = "".join(c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^A-Za-z0-9]+", " ", sin_tildes).split()).upper()


MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre",
         "Octubre", "Noviembre", "Diciembre"]


class DialogoNuevo(QDialog):
    """Pide los datos de cabecera para crear un anexo vacío."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nuevo anexo ATS")
        self.setMinimumWidth(460)
        cfg = QSettings()
        hoy = dt.date.today()
        anterior = (hoy.replace(day=1) - dt.timedelta(days=1))
        self.ruc = QLineEdit(cfg.value("nuevo/ruc", ""))
        self.ruc.setMaxLength(13)
        self.ruc.setPlaceholderText("13 dígitos, termina en 001")
        self.razon = QLineEdit(cfg.value("nuevo/razon", ""))
        self.razon.setMaxLength(500)
        self.anio = QSpinBox()
        self.anio.setRange(2002, 2100)
        self.anio.setValue(anterior.year)
        self.mes = QComboBox()
        self.mes.addItems([f"{i + 1:02d} - {m}" for i, m in enumerate(MESES)])
        self.mes.setCurrentIndex(anterior.month - 1)
        self.estab = QSpinBox()
        self.estab.setRange(1, 999)
        self.estab.setValue(int(cfg.value("nuevo/estab", 1)))
        self.semestral = QCheckBox("Anexo semestral (régimen RIMPE; solo con mes 06 o 12)")
        self.mes.currentIndexChanged.connect(self._mes_cambiado)
        self._mes_cambiado()

        form = QFormLayout()
        form.addRow("RUC del informante:", self.ruc)
        form.addRow("Razón social:", self.razon)
        form.addRow("Año:", self.anio)
        form.addRow("Mes:", self.mes)
        form.addRow("Establecimientos en el RUC:", self.estab)
        form.addRow("", self.semestral)
        self.aviso = QLabel()
        self.aviso.setStyleSheet("color: #c62828;")
        botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botones.button(QDialogButtonBox.Ok).setText("Crear")
        botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        botones.accepted.connect(self._aceptar)
        botones.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.aviso)
        lay.addWidget(botones)

    def _mes_cambiado(self) -> None:
        permitido = self.mes.currentIndex() in (5, 11)
        self.semestral.setEnabled(permitido)
        if not permitido:
            self.semestral.setChecked(False)

    def _aceptar(self) -> None:
        ruc = self.ruc.text().strip()
        razon = limpiar_texto(self.razon.text())
        if not (len(ruc) == 13 and ruc.isdigit() and ruc.endswith("001")):
            self.aviso.setText("El RUC debe tener 13 dígitos y terminar en 001.")
            return
        if len(razon) < 5:
            self.aviso.setText("La razón social debe tener al menos 5 caracteres.")
            return
        if not ruc_aceptado(ruc):
            r = QMessageBox.question(self, "RUC", "El RUC no cumple el dígito verificador. ¿Continuar de todos modos?")
            if r != QMessageBox.Yes:
                return
        cfg = QSettings()
        cfg.setValue("nuevo/ruc", ruc)
        cfg.setValue("nuevo/razon", razon)
        cfg.setValue("nuevo/estab", self.estab.value())
        self.datos = {
            "IdInformante": ruc,
            "razonSocial": razon,
            "Anio": str(self.anio.value()),
            "Mes": f"{self.mes.currentIndex() + 1:02d}",
            "numEstabRuc": f"{self.estab.value():03d}",
            "regimenMicroempresa": "SI" if self.semestral.isChecked() else "",
        }
        self.accept()


class DialogoEsquema(QDialog):
    """Importa el esquema oficial at.xsd desde DIMM o desde el plugin del ATS del SRI."""

    def __init__(self, parent=None, obligatorio: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Esquema del ATS")
        self.setMinimumWidth(560)
        self.importado = False
        texto = QLabel(
            "Para validar y generar el anexo, la aplicación usa el esquema oficial del SRI (<code>at.xsd</code>). "
            "Este archivo no se incluye con la aplicación: se toma de su instalación de DIMM o del plugin del ATS "
            "que publica el SRI (<i>ats.plugin.X.zip</i>).<br><br>Elija una de estas opciones:")
        texto.setWordWrap(True)
        texto.setTextFormat(Qt.RichText)
        b_auto = QPushButton("Buscar DIMM instalado")
        b_archivo = QPushButton("Elegir archivo (.zip, .jar o .xsd)…")
        b_carpeta = QPushButton("Elegir carpeta de DIMM…")
        b_auto.clicked.connect(self._auto)
        b_archivo.clicked.connect(self._archivo)
        b_carpeta.clicked.connect(self._carpeta)
        self.estado = QLabel()
        self.estado.setWordWrap(True)
        fila = QHBoxLayout()
        for b in (b_auto, b_archivo, b_carpeta):
            fila.addWidget(b)
        cerrar = QDialogButtonBox(QDialogButtonBox.Close)
        cerrar.button(QDialogButtonBox.Close).setText("Salir" if obligatorio else "Cerrar")
        cerrar.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(texto)
        lay.addLayout(fila)
        lay.addWidget(self.estado)
        lay.addWidget(cerrar)

    def _importar(self, ruta) -> None:
        try:
            enc = importador.importar_esquema(ruta)
        except Exception as e:  # noqa: BLE001 - se muestra al usuario
            self.estado.setText(f"<span style='color:#c62828'>No se pudo importar: {e}</span>")
            return
        self.importado = True
        QMessageBox.information(self, "Esquema importado", f"Se importó el esquema desde:\n{enc.origen}")
        self.accept()

    def _auto(self) -> None:
        lugares = importador.ubicaciones_probables()
        for lugar in lugares:
            try:
                importador.buscar_esquema(lugar)
            except (FileNotFoundError, OSError):
                continue
            self._importar(lugar)
            return
        self.estado.setText("No se encontró una instalación de DIMM en las carpetas habituales. "
                            "Use «Elegir archivo» o «Elegir carpeta».")

    def _archivo(self) -> None:
        ruta, _ = QFileDialog.getOpenFileName(self, "Plugin del ATS o esquema", "",
                                              "Plugin o esquema (*.zip *.jar *.xsd);;Todos (*)")
        if ruta:
            self._importar(ruta)

    def _carpeta(self) -> None:
        ruta = QFileDialog.getExistingDirectory(self, "Carpeta de instalación de DIMM")
        if ruta:
            self._importar(ruta)
