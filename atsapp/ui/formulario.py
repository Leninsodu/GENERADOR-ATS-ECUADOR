"""Formulario generado a partir del esquema para editar un elemento compuesto."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QGridLayout, QGroupBox, QHBoxLayout, QLabel, QPushButton, QToolButton,
                               QVBoxLayout, QWidget)

from ..catalogos import Catalogos
from ..documento import Nodo, crear_vacio
from ..esquema import DefElemento
from ..presentacion import etiqueta
from ..validacion import Mensaje
from .campos import CeldaCampo, crear_campo

ANCHO_COLUMNA = 340
MAX_COLUMNAS = 4


class GrillaAdaptable(QWidget):
    """Reparte sus celdas en 1..N columnas según el ancho disponible."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._celdas: list[QWidget] = []
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(16)
        self._grid.setVerticalSpacing(8)
        self._columnas = 0

    def agregar(self, celda: QWidget) -> None:
        self._celdas.append(celda)
        self._reacomodar(forzar=True)

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        self._reacomodar()

    def _reacomodar(self, forzar: bool = False) -> None:
        cols = max(1, min(MAX_COLUMNAS, self.width() // ANCHO_COLUMNA, len(self._celdas) or 1))
        if cols == self._columnas and not forzar:
            return
        for i in reversed(range(self._grid.count())):
            self._grid.takeAt(i)
        for c in range(MAX_COLUMNAS):
            self._grid.setColumnStretch(c, 1 if c < cols else 0)
        filas = (len(self._celdas) + cols - 1) // cols
        for f in range(self._grid.rowCount()):
            self._grid.setRowStretch(f, 0)
        for i, celda in enumerate(self._celdas):
            self._grid.addWidget(celda, i // cols, i % cols)
        self._grid.setRowStretch(filas, 1)  # el espacio sobrante va al final, no entre filas
        self._columnas = cols
        self.updateGeometry()


class ListaSimple(QWidget):
    """Edita un elemento simple repetible (por ejemplo, las formas de pago)."""

    cambiado = Signal()

    def __init__(self, contenedor: Nodo, defn: DefElemento, catalogos, periodo, parent=None):
        super().__init__(parent)
        self.contenedor = contenedor
        self.defn = defn
        self.catalogos = catalogos
        self.periodo = periodo
        self._filas: list[tuple[QWidget, object]] = []
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(4)
        self._boton = QPushButton(f"Agregar {etiqueta(defn.nombre).lower()}")
        self._boton.clicked.connect(lambda: (self._agregar_fila(""), self._sincronizar()))
        fila_boton = QHBoxLayout()
        fila_boton.addWidget(self._boton)
        fila_boton.addStretch(1)
        self._lay.addLayout(fila_boton)
        valores = [h.valor for h in contenedor.lista(defn.nombre)]
        for v in valores or ([""] if defn.es_obligatorio else []):
            self._agregar_fila(v)

    def _agregar_fila(self, valor: str) -> None:
        if self.defn.max_ocurr is not None and len(self._filas) >= self.defn.max_ocurr:
            return
        fila = QWidget()
        lay = QHBoxLayout(fila)
        lay.setContentsMargins(0, 0, 0, 0)
        campo = crear_campo(self.defn, self.catalogos, self.periodo)
        campo.poner_valor(valor)
        campo.cambiado.connect(self._sincronizar)
        quitar = QToolButton()
        quitar.setText("✕")
        quitar.setToolTip("Quitar")
        quitar.clicked.connect(lambda: self._quitar(fila))
        lay.addWidget(campo, 1)
        lay.addWidget(quitar)
        self._lay.insertWidget(len(self._filas), fila)
        self._filas.append((fila, campo))

    def _quitar(self, fila: QWidget) -> None:
        self._filas = [(f, c) for f, c in self._filas if f is not fila]
        fila.deleteLater()
        self._sincronizar()

    def _sincronizar(self) -> None:
        for h in self.contenedor.lista(self.defn.nombre):
            self.contenedor.eliminar(h)
        for _f, campo in self._filas:
            v = campo.valor()
            if v:
                self.contenedor.agregar(self.defn.nombre).valor = v
        self.cambiado.emit()

    def errores(self) -> list[str]:
        problemas = []
        for _f, campo in self._filas:
            v = campo.valor()
            if v:
                problemas += self.defn.tipo.errores(v)
        return problemas


class FormularioNodo(QWidget):
    """Muestra y edita los hijos de un nodo compuesto. Los cambios se aplican al nodo."""

    cambiado = Signal()

    def __init__(self, nodo: Nodo, catalogos: Catalogos | None, periodo=(None, None),
                 solo_simples: bool = False, anidado: bool = False, parent=None):
        super().__init__(parent)
        self.nodo = nodo
        self.catalogos = catalogos
        self.periodo = periodo
        self.celdas: dict[str, CeldaCampo] = {}
        self.subformularios: dict[str, FormularioNodo] = {}
        self.grupos: dict[str, QGroupBox] = {}
        self.listas: dict[str, QWidget] = {}
        self._guardados: dict[str, Nodo] = {}
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        grilla: GrillaAdaptable | None = None
        for d in nodo.defn.hijos:
            if d.es_simple and not d.es_repetible:
                if grilla is None:
                    grilla = GrillaAdaptable()
                    lay.addWidget(grilla)
                grilla.agregar(self._crear_celda(d))
                continue
            if solo_simples:
                continue
            grilla = None
            lay.addWidget(self._crear_seccion(d))
        if not anidado:
            lay.addStretch(1)

    # --- construcción ------------------------------------------------------------
    def _crear_celda(self, d: DefElemento) -> CeldaCampo:
        campo = crear_campo(d, self.catalogos, self.periodo)
        campo.poner_valor(self.nodo.texto(d.nombre))
        celda = CeldaCampo(d, campo)
        campo.cambiado.connect(lambda d=d, celda=celda: self._al_cambiar(d, celda))
        self.celdas[d.nombre] = celda
        valor = campo.valor()
        if valor:
            celda.mostrar_errores(d.tipo.errores(valor))
        return celda

    def _crear_seccion(self, d: DefElemento) -> QWidget:
        from .tabla import PanelLista

        grupo = QGroupBox(etiqueta(d.nombre) + (" *" if d.es_obligatorio else ""))
        grupo.setToolTip(f"Campo XML: <code>{d.nombre}</code>" + (f"<br>{d.documentacion}" if d.documentacion else ""))
        self.grupos[d.nombre] = grupo
        lay = QVBoxLayout(grupo)
        if d.es_repetible and d.es_simple:
            w = ListaSimple(self.nodo, d, self.catalogos, self.periodo)
            w.cambiado.connect(self.cambiado)
            self.listas[d.nombre] = w
            lay.addWidget(w)
            return grupo
        if d.es_repetible:
            w = PanelLista(self.nodo, d, self.catalogos, self.periodo, compacto=True)
            w.modificado.connect(self.cambiado)
            self.listas[d.nombre] = w
            lay.addWidget(w)
            return grupo
        # compuesto no repetible
        hijo = self.nodo.hijo(d.nombre)
        unico = d.hijos[0] if len(d.hijos) == 1 else None
        if unico is not None and unico.es_repetible:
            # contenedor de una lista (formasDePago, air, reembolsos...)
            if hijo is None:
                hijo = self.nodo.agregar(d.nombre, crear_vacio(d))
                for h in list(hijo.hijos):  # sin filas vacías iniciales
                    if not unico.es_simple:
                        hijo.eliminar(h)
            if unico.es_simple:
                w = ListaSimple(hijo, unico, self.catalogos, self.periodo)
                w.cambiado.connect(self.cambiado)
            else:
                w = PanelLista(hijo, unico, self.catalogos, self.periodo, compacto=True)
                w.modificado.connect(self.cambiado)
            self.listas[d.nombre] = w
            lay.addWidget(w)
            return grupo
        if hijo is None:
            hijo = crear_vacio(d)
            if d.es_obligatorio:
                self.nodo.agregar(d.nombre, hijo)
            else:
                self._guardados[d.nombre] = hijo
        sub = FormularioNodo(hijo, self.catalogos, self.periodo, anidado=True)
        sub.cambiado.connect(self.cambiado)
        self.subformularios[d.nombre] = sub
        lay.addWidget(sub)
        if not d.es_obligatorio:
            grupo.setCheckable(True)
            presente = self.nodo.hijo(d.nombre) is not None
            grupo.setChecked(presente)
            sub.setVisible(presente)
            grupo.toggled.connect(lambda activo, d=d, sub=sub: self._alternar(d, sub, activo))
        return grupo

    # --- eventos -------------------------------------------------------------------
    def _al_cambiar(self, d: DefElemento, celda: CeldaCampo) -> None:
        v = celda.campo.valor()
        actual = self.nodo.hijo(d.nombre)
        if v == "" and not d.es_obligatorio:
            if actual is not None:
                self.nodo.eliminar(actual)
        else:
            self.nodo.poner(d.nombre, v)
        celda.mostrar_errores(d.tipo.errores(v) if v else [])
        self.cambiado.emit()

    def _alternar(self, d: DefElemento, sub: "FormularioNodo", activo: bool) -> None:
        actual = self.nodo.hijo(d.nombre)
        if activo and actual is None:
            self.nodo.agregar(d.nombre, self._guardados.pop(d.nombre, sub.nodo))
        elif not activo and actual is not None:
            self._guardados[d.nombre] = actual
            self.nodo.eliminar(actual)
        sub.setVisible(activo)
        self.cambiado.emit()

    # --- validación visible ------------------------------------------------------------
    def limpiar_errores(self) -> None:
        for celda in self.celdas.values():
            v = celda.campo.valor()
            celda.mostrar_errores(celda.defn.tipo.errores(v) if v else [])
        for sub in self.subformularios.values():
            sub.limpiar_errores()

    def mostrar_mensajes(self, mensajes: list[Mensaje], base: str) -> list[Mensaje]:
        """Marca en los campos los mensajes cuya ruta cae dentro de este formulario.

        Devuelve los mensajes que no se pudieron asociar a un campo concreto.
        """
        por_campo: dict[str, list[str]] = {}
        sobrantes: list[Mensaje] = []
        por_sub: dict[str, list[Mensaje]] = {}
        for m in mensajes:
            if not m.ruta.startswith(base + "/"):
                sobrantes.append(m)
                continue
            resto = m.ruta[len(base) + 1:]
            primero = resto.split("/", 1)[0]
            nombre = primero.split("[", 1)[0]
            if "/" not in resto and nombre in self.celdas:
                por_campo.setdefault(nombre, []).append(m.texto)
            elif nombre in self.subformularios and "[" not in primero:
                por_sub.setdefault(nombre, []).append(m)
            else:
                sobrantes.append(m)
        for nombre, celda in self.celdas.items():
            if nombre in por_campo:
                celda.mostrar_errores(por_campo[nombre])
        for nombre, lista in por_sub.items():
            sobrantes += self.subformularios[nombre].mostrar_mensajes(lista, f"{base}/{nombre}")
        return sobrantes

    def enfocar(self, ruta_relativa: str) -> bool:
        partes = [p for p in ruta_relativa.strip("/").split("/") if p]
        if not partes:
            return False
        nombre = partes[0].split("[", 1)[0]
        if len(partes) == 1 and nombre in self.celdas:
            ctrl = self.celdas[nombre].campo.control()
            ctrl.setFocus()
            self._asegurar_visible(ctrl)
            return True
        if nombre in self.subformularios:
            return self.subformularios[nombre].enfocar("/".join(partes[1:]))
        if nombre in self.grupos:
            self.grupos[nombre].setFocus()
            self._asegurar_visible(self.grupos[nombre])
            return True
        return False

    def _asegurar_visible(self, w: QWidget) -> None:
        from PySide6.QtWidgets import QScrollArea

        padre = self.parent()
        while padre is not None and not isinstance(padre, QScrollArea):
            padre = padre.parent()
        if padre is not None:
            padre.ensureWidgetVisible(w, 50, 80)


def etiqueta_seccion(texto: str) -> QLabel:
    lbl = QLabel(texto)
    f = lbl.font()
    f.setBold(True)
    lbl.setFont(f)
    return lbl
