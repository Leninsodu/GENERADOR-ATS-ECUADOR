"""Tabla de registros repetibles (compras, ventas, retenciones...) con su barra de acciones."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Callable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QMenu,
                               QMessageBox, QPushButton, QStyle, QTableView, QVBoxLayout, QWidget)

from .. import proveedores
from ..catalogos import Catalogos
from ..documento import Nodo, crear_vacio
from ..esquema import DefElemento
from ..presentacion import columnas, columnas_total, etiqueta, etiqueta_corta
from ..validacion import Mensaje, Severidad

ROL_ORDEN = Qt.UserRole + 1
# Columnas extra que muestran el nombre recordado de una identificación (el ATS solo guarda el número)
COLUMNAS_NOMBRE = {"idProv": "Nombre", "idCliente": "Nombre"}


class ModeloLista(QAbstractTableModel):
    def __init__(self, contenedor: Nodo, defn_item: DefElemento, catalogos: Catalogos | None, parent=None):
        super().__init__(parent)
        self.contenedor = contenedor
        self.defn = defn_item
        self.catalogos = catalogos
        self.cols: list[tuple[DefElemento, bool]] = []  # (campo, es_columna_de_nombre)
        for d in columnas(defn_item):
            self.cols.append((d, False))
            if d.nombre in COLUMNAS_NOMBRE:
                self.cols.append((d, True))
        self.estados: dict[int, Severidad] = {}
        self._filas: list[Nodo] = contenedor.lista(defn_item.nombre)

    def filas(self) -> list[Nodo]:
        return self._filas

    def refrescar(self, contenedor: Nodo | None = None) -> None:
        self.beginResetModel()
        if contenedor is not None:
            self.contenedor = contenedor
        self._filas = self.contenedor.lista(self.defn.nombre)
        self.endResetModel()

    def poner_estados(self, estados: dict[int, Severidad]) -> None:
        self.estados = estados
        if self._filas:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self._filas) - 1, len(self.cols)),
                                  [Qt.DecorationRole, Qt.BackgroundRole, Qt.ToolTipRole])

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._filas)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self.cols) + 1

    def headerData(self, seccion, orientacion, rol=Qt.DisplayRole):
        if orientacion == Qt.Horizontal:
            if seccion == 0:
                return "N.º" if rol == Qt.DisplayRole else None
            d, es_nombre = self.cols[seccion - 1]
            if es_nombre:
                if rol == Qt.DisplayRole:
                    return COLUMNAS_NOMBRE[d.nombre]
                if rol == Qt.ToolTipRole:
                    return "Nombre tomado de los comprobantes importados (no forma parte del ATS)"
                return None
            if rol == Qt.DisplayRole:
                return etiqueta_corta(d.nombre)
            if rol == Qt.ToolTipRole:
                return f"{etiqueta(d.nombre)} ({d.nombre})"
        return None

    def data(self, indice: QModelIndex, rol=Qt.DisplayRole):
        if not indice.isValid():
            return None
        fila, col = indice.row(), indice.column()
        nodo = self._filas[fila]
        if col == 0:
            if rol in (Qt.DisplayRole, ROL_ORDEN):
                return fila + 1
            if rol == Qt.DecorationRole and fila in self.estados:
                estilo = QStyle.SP_MessageBoxCritical if self.estados[fila] is Severidad.ERROR else QStyle.SP_MessageBoxWarning
                from PySide6.QtWidgets import QApplication
                return QApplication.style().standardIcon(estilo)
            if rol == Qt.ToolTipRole and fila in self.estados:
                return "Tiene errores" if self.estados[fila] is Severidad.ERROR else "Tiene advertencias"
            if rol == Qt.TextAlignmentRole:
                return int(Qt.AlignRight | Qt.AlignVCenter)
            return None
        d, es_nombre = self.cols[col - 1]
        valor = nodo.texto(d.nombre)
        if es_nombre:
            if rol in (Qt.DisplayRole, ROL_ORDEN, Qt.ToolTipRole):
                return proveedores.nombre(valor)
            if rol == Qt.BackgroundRole and self.estados.get(fila) is Severidad.ERROR:
                return QColor(198, 40, 40, 28)
            return None
        if rol == Qt.DisplayRole:
            return valor
        if rol == ROL_ORDEN:
            if d.tipo is not None and (d.tipo.es_numerico or _parece_numero(valor)):
                try:
                    return float(Decimal(valor))
                except (InvalidOperation, ValueError):
                    return 0.0
            if len(valor) == 10 and valor[2:3] == "/" and valor[5:6] == "/":
                return valor[6:] + valor[3:5] + valor[:2]
            return valor
        if rol == Qt.ToolTipRole and self.catalogos is not None and valor:
            return self.catalogos.descripcion(d.nombre, valor)
        if rol == Qt.TextAlignmentRole and _parece_numero(valor) and "." in valor:
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if rol == Qt.BackgroundRole and self.estados.get(fila) is Severidad.ERROR:
            return QColor(198, 40, 40, 28)
        return None


def _parece_numero(v: str) -> bool:
    return bool(v) and v.replace(".", "", 1).isdigit()


class VistaTabla(QTableView):
    """Tabla que muestra un texto de ayuda tenue (marca de agua) en el espacio libre."""

    marca_agua: str = ""

    def paintEvent(self, evento) -> None:
        super().paintEvent(evento)
        if not self.marca_agua:
            return
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QPainter

        filas = self.model().rowCount() if self.model() else 0
        alto = self.viewport().height()
        inicio = 0
        if filas:
            ultima = self.rowViewportPosition(filas - 1) + self.rowHeight(filas - 1)
            inicio = max(ultima, 0)
        libre = QRect(0, inicio, self.viewport().width(), alto - inicio)
        if libre.height() < 70:
            return
        p = QPainter(self.viewport())
        color = self.palette().color(self.palette().ColorRole.Text)
        color.setAlpha(70)
        p.setPen(color)
        fuente = p.font()
        fuente.setPointSizeF(fuente.pointSizeF() * (1.6 if libre.height() > 160 else 1.2))
        fuente.setBold(True)
        p.setFont(fuente)
        p.drawText(libre.adjusted(20, 10, -20, -10), int(Qt.AlignCenter | Qt.TextWordWrap), self.marca_agua)
        p.end()


class PanelLista(QWidget):
    """Lista editable de registros de un mismo tipo."""

    modificado = Signal()
    seleccion_cambiada = Signal()

    def __init__(self, contenedor: Nodo, defn_item: DefElemento, catalogos: Catalogos | None,
                 periodo=(None, None), compacto: bool = False,
                 validador: Callable[[Nodo | None, Nodo], tuple[list[Mensaje], str]] | None = None, parent=None):
        super().__init__(parent)
        self.defn = defn_item
        self.catalogos = catalogos
        self.periodo = periodo
        self.validador = validador
        self.modelo = ModeloLista(contenedor, defn_item, catalogos, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.modelo)
        self.proxy.setSortRole(ROL_ORDEN)
        self.proxy.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1)

        self.vista = VistaTabla()
        self.vista.setModel(self.proxy)
        self.vista.setSortingEnabled(True)
        self.vista.sortByColumn(0, Qt.AscendingOrder)
        self.vista.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.vista.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.vista.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.vista.setAlternatingRowColors(True)
        self.vista.setWordWrap(False)
        self.vista.verticalHeader().hide()
        self.vista.verticalHeader().setDefaultSectionSize(self.vista.fontMetrics().height() + 10)
        cab = self.vista.horizontalHeader()
        cab.setSectionResizeMode(QHeaderView.Interactive)
        cab.setStretchLastSection(True)
        cab.setMinimumSectionSize(40)
        self.vista.doubleClicked.connect(lambda _i: self.editar())
        self.vista.selectionModel().selectionChanged.connect(lambda *_: self._actualizar_botones())
        self.vista.setContextMenuPolicy(Qt.CustomContextMenu)
        self.vista.customContextMenuRequested.connect(self._menu_contextual)

        nombre = etiqueta(defn_item.nombre).lower()
        self.b_agregar = QPushButton(f"Agregar {nombre}")
        self.b_editar = QPushButton("Editar")
        self.b_duplicar = QPushButton("Duplicar")
        self.b_eliminar = QPushButton("Eliminar")
        self.b_agregar.clicked.connect(self.agregar)
        self.b_editar.clicked.connect(self.editar)
        self.b_duplicar.clicked.connect(self.duplicar)
        self.b_eliminar.clicked.connect(self.eliminar)
        self.buscar = QLineEdit()
        self.buscar.setPlaceholderText("Buscar…")
        self.buscar.setClearButtonEnabled(True)
        self.buscar.textChanged.connect(self.proxy.setFilterFixedString)
        self.totales = QLabel()
        self.totales.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.totales.setWordWrap(True)

        self.barra = barra = QHBoxLayout()
        for b in (self.b_agregar, self.b_editar, self.b_duplicar, self.b_eliminar):
            barra.addWidget(b)
        barra.addStretch(1)
        barra.addWidget(self.buscar, 0 if compacto else 1)
        if compacto:
            self.buscar.hide()

        lay = QVBoxLayout(self)
        m = 0 if compacto else 6
        lay.setContentsMargins(m, m, m, m)
        lay.addLayout(barra)
        lay.addWidget(self.vista, 1)
        lay.addWidget(self.totales)
        if compacto:
            self.vista.setMinimumHeight(110)
            self.vista.setMaximumHeight(220)

        for texto, atajo, funcion in (("Eliminar", QKeySequence.Delete, self.eliminar),
                                      ("Editar", QKeySequence(Qt.Key_Return), self.editar)):
            a = QAction(texto, self.vista)
            a.setShortcut(atajo)
            a.setShortcutContext(Qt.WidgetShortcut)
            a.triggered.connect(funcion)
            self.vista.addAction(a)
        self._ajustar_columnas()
        self._actualizar()

    # --- utilidades -----------------------------------------------------------------
    @property
    def contenedor(self) -> Nodo:
        return self.modelo.contenedor

    def poner_contenedor(self, contenedor: Nodo, periodo=None) -> None:
        if periodo is not None:
            self.periodo = periodo
        self.modelo.refrescar(contenedor)
        self._actualizar()

    def _ajustar_columnas(self) -> None:
        fm = self.vista.fontMetrics()
        self.vista.setColumnWidth(0, fm.horizontalAdvance("0000") + 36)
        for i, (d, es_nombre) in enumerate(self.modelo.cols, start=1):
            if es_nombre:
                self.vista.setColumnWidth(i, fm.horizontalAdvance("0" * 22))
                continue
            ancho_titulo = fm.horizontalAdvance(etiqueta_corta(d.nombre)) + 24
            ancho_dato = fm.horizontalAdvance("0" * min(_ancho_tipico(d), 20)) + 16
            self.vista.setColumnWidth(i, min(max(ancho_titulo, ancho_dato), 260))

    def _filas_seleccionadas(self) -> list[int]:
        filas = {self.proxy.mapToSource(i).row() for i in self.vista.selectionModel().selectedRows()}
        return sorted(filas)

    def _actualizar_botones(self) -> None:
        n = len(self._filas_seleccionadas())
        self.b_editar.setEnabled(n == 1)
        self.b_duplicar.setEnabled(n == 1)
        self.b_eliminar.setEnabled(n >= 1)
        maximo = self.defn.max_ocurr
        self.b_agregar.setEnabled(maximo is None or len(self.modelo.filas()) < maximo)
        self.seleccion_cambiada.emit()

    def _actualizar(self) -> None:
        self._actualizar_botones()
        filas = self.modelo.filas()
        partes = [f"{len(filas)} registro(s)"]
        for campo in columnas_total(self.defn):
            total = Decimal(0)
            for f in filas:
                try:
                    total += Decimal(f.texto(campo) or 0)
                except InvalidOperation:
                    pass
            partes.append(f"{etiqueta(campo)}: {total:,.2f}")
        self.totales.setText("   ·   ".join(partes))

    def _menu_contextual(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("Editar", self.editar).setEnabled(self.b_editar.isEnabled())
        menu.addAction("Duplicar", self.duplicar).setEnabled(self.b_duplicar.isEnabled())
        menu.addAction("Eliminar", self.eliminar).setEnabled(self.b_eliminar.isEnabled())
        menu.exec(self.vista.viewport().mapToGlobal(pos))

    def seleccionar(self, fila: int) -> None:
        indice = self.proxy.mapFromSource(self.modelo.index(fila, 0))
        if not indice.isValid():  # oculto por el filtro
            self.buscar.clear()
            indice = self.proxy.mapFromSource(self.modelo.index(fila, 0))
        self.vista.selectRow(indice.row())
        self.vista.scrollTo(indice, QAbstractItemView.PositionAtCenter)

    def poner_mensajes(self, mensajes: list[Mensaje]) -> None:
        """Marca las filas con errores o advertencias."""
        base = self.contenedor.ruta() + "/" + self.defn.nombre
        unico = len(self.modelo.filas()) == 1
        estados: dict[int, Severidad] = {}
        for m in mensajes:
            if not m.ruta.startswith(base):
                continue
            resto = m.ruta[len(base):]
            if resto.startswith("["):
                fila = int(resto[1:resto.index("]")]) - 1
            elif unico and (resto == "" or resto.startswith("/")):
                fila = 0
            else:
                continue
            estados[fila] = max(estados.get(fila, m.severidad), m.severidad)
        self.modelo.poner_estados(estados)

    # --- acciones -----------------------------------------------------------------------
    def _dialogo(self, nodo: Nodo, original: Nodo | None, titulo: str, enfocar: str | None = None) -> bool:
        from .editor import DialogoRegistro

        dlg = DialogoRegistro(nodo, self.catalogos, self.periodo, titulo, self, original=original,
                              contenedor=self.contenedor, validador=self.validador, enfocar=enfocar)
        return dlg.exec() == DialogoRegistro.Accepted

    def agregar(self) -> None:
        nuevo = crear_vacio(self.defn)
        n = len(self.modelo.filas()) + 1
        if self._dialogo(nuevo, None, f"Nuevo registro: {etiqueta(self.defn.nombre)} {n}"):
            self.contenedor.agregar(self.defn.nombre, nuevo)
            self._tras_cambio()
            self.seleccionar(self.modelo.filas().index(nuevo))

    def editar(self, fila: int | None = None, enfocar: str | None = None) -> None:
        if fila is None:
            sel = self._filas_seleccionadas()
            if len(sel) != 1:
                return
            fila = sel[0]
        original = self.modelo.filas()[fila]
        copia = original.copiar()
        if self._dialogo(copia, original, f"{etiqueta(self.defn.nombre)} {fila + 1}", enfocar):
            self.contenedor.reemplazar(original, copia)
            self._tras_cambio()
            self.seleccionar(fila)

    def duplicar(self) -> None:
        sel = self._filas_seleccionadas()
        if len(sel) != 1:
            return
        original = self.modelo.filas()[sel[0]]
        copia = original.copiar()
        n = len(self.modelo.filas()) + 1
        if self._dialogo(copia, None, f"Nuevo registro (copia): {etiqueta(self.defn.nombre)} {n}"):
            self.contenedor.insertar_despues(self.modelo.filas()[-1], copia)
            self._tras_cambio()
            self.seleccionar(self.modelo.filas().index(copia))

    def eliminar(self) -> None:
        sel = self._filas_seleccionadas()
        if not sel:
            return
        texto = f"¿Eliminar {len(sel)} registro(s) de {etiqueta(self.defn.nombre).lower()}?"
        if QMessageBox.question(self, "Eliminar", texto) != QMessageBox.Yes:
            return
        filas = self.modelo.filas()
        for i in reversed(sel):
            self.contenedor.eliminar(filas[i])
        self._tras_cambio()

    def _tras_cambio(self) -> None:
        self.modelo.refrescar()
        self._actualizar()
        self.modificado.emit()


def _ancho_tipico(d: DefElemento) -> int:
    t = d.tipo
    if t is None:
        return 10
    if t.longitud:
        return t.longitud
    if t.es_fecha:
        return 10
    if t.max_longitud:
        return min(t.max_longitud, 20)
    return 12
