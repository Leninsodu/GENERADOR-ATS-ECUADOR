"""Controles de edición para valores simples, generados según el tipo del esquema."""

from __future__ import annotations

import datetime as dt
import re

from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtWidgets import (QCalendarWidget, QComboBox, QCompleter, QHBoxLayout, QLabel, QLineEdit,
                               QMenu, QSizePolicy, QToolButton, QVBoxLayout, QWidget, QWidgetAction)

from ..catalogos import Catalogos
from ..esquema import DefElemento
from ..presentacion import etiqueta

SEPARADOR = " — "


class Campo(QWidget):
    """Interfaz común: valor(), poner_valor(), mostrar_errores(). Emite `cambiado`."""

    cambiado = Signal()

    def valor(self) -> str:
        raise NotImplementedError

    def poner_valor(self, valor: str) -> None:
        raise NotImplementedError

    def control(self) -> QWidget:
        raise NotImplementedError


class CampoTexto(Campo):
    def __init__(self, defn: DefElemento, parent=None):
        super().__init__(parent)
        self.defn = defn
        self.edit = QLineEdit()
        tipo = defn.tipo
        if tipo.max_longitud:
            self.edit.setMaxLength(tipo.max_longitud)
        elif tipo.longitud:
            self.edit.setMaxLength(tipo.longitud)
        self.numerico = tipo.base == "decimal" or _es_monto(defn)
        if self.numerico:
            self.edit.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.edit)
        self.edit.textEdited.connect(lambda _t: self.cambiado.emit())
        self.edit.editingFinished.connect(self._normalizar)

    def _normalizar(self) -> None:
        if not self.numerico:
            return
        nuevo = normalizar_numero(self.edit.text(), _decimales(self.defn))
        if nuevo != self.edit.text():
            self.edit.setText(nuevo)
            self.cambiado.emit()

    def valor(self) -> str:
        return self.edit.text().strip()

    def poner_valor(self, valor: str) -> None:
        self.edit.setText(valor)

    def control(self) -> QWidget:
        return self.edit


class CampoFecha(Campo):
    def __init__(self, defn: DefElemento, parent=None):
        super().__init__(parent)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("dd/mm/aaaa")
        self.edit.setMaxLength(10)
        boton = QToolButton()
        boton.setText("📅")
        boton.setToolTip("Elegir en el calendario")
        boton.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(boton)
        self.calendario = QCalendarWidget()
        accion = QWidgetAction(menu)
        accion.setDefaultWidget(self.calendario)
        menu.addAction(accion)
        menu.aboutToShow.connect(self._preparar_calendario)
        self.calendario.clicked.connect(lambda d: (self._elegir(d), menu.close()))
        boton.setMenu(menu)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self.edit)
        lay.addWidget(boton)
        self.edit.textEdited.connect(lambda _t: self.cambiado.emit())
        self.edit.editingFinished.connect(self._normalizar)

    def _preparar_calendario(self) -> None:
        try:
            f = dt.datetime.strptime(self.valor(), "%d/%m/%Y").date()
            self.calendario.setSelectedDate(QDate(f.year, f.month, f.day))
        except ValueError:
            pass

    def _elegir(self, d: QDate) -> None:
        self.edit.setText(d.toString("dd/MM/yyyy"))
        self.cambiado.emit()

    def _normalizar(self) -> None:
        nuevo = normalizar_fecha(self.edit.text())
        if nuevo != self.edit.text():
            self.edit.setText(nuevo)
            self.cambiado.emit()

    def valor(self) -> str:
        return self.edit.text().strip()

    def poner_valor(self, valor: str) -> None:
        self.edit.setText(valor)

    def control(self) -> QWidget:
        return self.edit


class CampoOpciones(Campo):
    """Lista desplegable con código y descripción. Editable cuando viene de un catálogo."""

    def __init__(self, defn: DefElemento, opciones: list[tuple[str, str]], editable: bool, parent=None):
        super().__init__(parent)
        self.combo = QComboBox()
        self.combo.setEditable(editable)
        self.combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.combo.setMinimumContentsLength(12)
        self.combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._codigos: list[str] = []
        self.combo.addItem("", "")
        self._codigos.append("")
        for codigo, desc in opciones:
            self.combo.addItem(f"{codigo}{SEPARADOR}{desc}" if desc else codigo, codigo)
            self._codigos.append(codigo)
        if editable:
            completer = QCompleter(self.combo.model(), self.combo)
            completer.setFilterMode(Qt.MatchContains)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            completer.setCompletionMode(QCompleter.PopupCompletion)
            self.combo.setCompleter(completer)
            self.combo.lineEdit().editingFinished.connect(self._ajustar_texto)
            self.combo.editTextChanged.connect(lambda _t: self.cambiado.emit())
        self.combo.currentIndexChanged.connect(lambda _i: self.cambiado.emit())
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.combo)

    def _ajustar_texto(self) -> None:
        codigo = self.valor()
        if codigo in self._codigos:
            i = self._codigos.index(codigo)
            if self.combo.currentIndex() != i or self.combo.currentText() != self.combo.itemText(i):
                self.combo.setCurrentIndex(i)
                self.combo.setEditText(self.combo.itemText(i))
            self.combo.lineEdit().setCursorPosition(0)

    def valor(self) -> str:
        texto = self.combo.currentText().strip()
        i = self.combo.findText(texto)
        if i >= 0:
            return self.combo.itemData(i) or ""
        return texto.split(SEPARADOR, 1)[0].strip()

    def poner_valor(self, valor: str) -> None:
        self._poner(valor)
        if self.combo.isEditable():
            self.combo.lineEdit().setCursorPosition(0)

    def _poner(self, valor: str) -> None:
        if valor in self._codigos:
            self.combo.setCurrentIndex(self._codigos.index(valor))
        elif self.combo.isEditable():
            self.combo.setCurrentIndex(-1)
            self.combo.setEditText(valor)
        else:
            self.combo.addItem(valor, valor)
            self._codigos.append(valor)
            self.combo.setCurrentIndex(len(self._codigos) - 1)

    def control(self) -> QWidget:
        return self.combo


def crear_campo(defn: DefElemento, catalogos: Catalogos | None, periodo=(None, None)) -> Campo:
    tipo = defn.tipo
    tabla = catalogos.tabla_de(defn.nombre) if catalogos else None
    if tipo.enumeracion:
        opciones = []
        for v in tipo.enumeracion:
            fila = tabla.buscar(v) if tabla else None
            opciones.append((v, fila.descripcion if fila else ""))
        return CampoOpciones(defn, opciones, editable=False)
    if tabla is not None:
        filas = tabla.vigentes(*periodo) or tabla.filas
        return CampoOpciones(defn, [(f.codigo, f.descripcion) for f in filas], editable=True)
    if tipo.es_fecha:
        return CampoFecha(defn)
    return CampoTexto(defn)


class CeldaCampo(QWidget):
    """Etiqueta + control + texto de error, como una unidad que la grilla reacomoda."""

    def __init__(self, defn: DefElemento, campo: Campo, parent=None):
        super().__init__(parent)
        self.defn = defn
        self.campo = campo
        texto = etiqueta(defn.nombre) + (" *" if defn.es_obligatorio else "")
        self.etiqueta = QLabel(texto)
        self.etiqueta.setBuddy(campo.control())
        self.etiqueta.setWordWrap(True)
        ayuda = f"<b>{etiqueta(defn.nombre)}</b><br>Campo XML: <code>{defn.nombre}</code>"
        if defn.documentacion:
            ayuda += f"<br>{defn.documentacion}"
        self.setToolTip(ayuda)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #c62828; font-size: 11px;")
        self.error.hide()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self.etiqueta)
        lay.addWidget(campo)
        lay.addWidget(self.error)

    def mostrar_errores(self, errores: list[str]) -> None:
        ctrl = self.campo.control()
        if errores:
            self.error.setText("; ".join(errores))
            self.error.show()
            ctrl.setStyleSheet("border: 1px solid #c62828; border-radius: 3px; padding: 2px;")
        else:
            self.error.hide()
            ctrl.setStyleSheet("")


def _es_monto(defn: DefElemento) -> bool:
    return any("\\.[0-9]{2}" in p for g in defn.tipo.patrones for p in g)


def _decimales(defn: DefElemento) -> int | None:
    if _es_monto(defn):
        return 2
    return defn.tipo.decimales


def normalizar_numero(texto: str, decimales: int | None) -> str:
    """Acepta '1.234,56', '1,234.56', '1234,5' y devuelve '1234.56'."""
    t = texto.strip().replace(" ", "").replace("$", "")
    if not t:
        return ""
    if "," in t and "." in t:
        if t.rfind(",") > t.rfind("."):
            t = t.replace(".", "").replace(",", ".")
        else:
            t = t.replace(",", "")
    elif "," in t:
        t = t.replace(",", ".")
    if not re.fullmatch(r"-?\d+(\.\d*)?|-?\.\d+", t):
        return texto
    if decimales:
        from decimal import ROUND_HALF_UP, Decimal
        return str(Decimal(t).quantize(Decimal(1).scaleb(-decimales), rounding=ROUND_HALF_UP))
    return t


def normalizar_fecha(texto: str) -> str:
    """Acepta '7/5/2026', '07-05-2026', '07052026' y devuelve '07/05/2026'."""
    t = texto.strip()
    if not t:
        return ""
    m = re.fullmatch(r"(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4})", t) or re.fullmatch(r"(\d{2})(\d{2})(\d{4})", t)
    if not m:
        return texto
    d, mes, a = m.groups()
    return f"{int(d):02d}/{int(mes):02d}/{a}"
