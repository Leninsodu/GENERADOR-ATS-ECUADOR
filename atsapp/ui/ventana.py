"""Ventana principal del editor ATS."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from PySide6.QtCore import QByteArray, QSettings, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QGuiApplication, QKeySequence
from PySide6.QtWidgets import (QDockWidget, QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel, QMainWindow,
                               QMessageBox, QPushButton, QScrollArea, QStackedWidget, QTabWidget, QVBoxLayout,
                               QWidget)

from .. import __version__, comprobantes, proveedores, registro_ventas, retenciones
from ..catalogos import Catalogos, rango_periodo
from ..documento import Documento, Nodo, crear_vacio
from ..esquema import Esquema
from ..presentacion import etiqueta
from ..reglas import dec
from ..reglas import total_ventas as total_ventas_de
from ..validacion import Mensaje, validar_documento
from .dialogos import DialogoEsquema, DialogoNuevo
from .importar_comprobantes import DialogoImportarComprobantes
from .formulario import FormularioNodo
from .mensajes import PanelMensajes
from .tabla import PanelLista

FILTRO_ABRIR = "Anexo ATS (*.xml *.zip);;XML (*.xml);;ZIP (*.zip);;Todos (*)"
MAX_RECIENTES = 8


class VentanaPrincipal(QMainWindow):
    def __init__(self, esquema: Esquema, catalogos: Catalogos):
        super().__init__()
        self.esquema = esquema
        self.catalogos = catalogos
        self.doc: Documento | None = None
        self.ruta: Path | None = None
        self.modificado = False
        self.mensajes: list[Mensaje] = []
        self.paneles: dict[str, PanelLista] = {}
        self.formularios: dict[str, FormularioNodo] = {}
        self.form_cabecera: FormularioNodo | None = None
        self.setAcceptDrops(True)

        self._crear_acciones()
        self.pestanas = QTabWidget()
        self.pestanas.setDocumentMode(True)
        self.pila = QStackedWidget()
        self.pila.addWidget(self._crear_bienvenida())
        self.pila.addWidget(self.pestanas)
        self.setCentralWidget(self.pila)

        self.panel_mensajes = PanelMensajes()
        self.panel_mensajes.activado.connect(self.navegar)
        self.dock = QDockWidget("Validación", self)
        self.dock.setObjectName("dock_validacion")
        self.dock.setWidget(self.panel_mensajes)
        self.dock.setFeatures(QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock)

        self.lbl_estado = QLabel()
        self.statusBar().addPermanentWidget(self.lbl_estado)
        self._temporizador = QTimer(self, singleShot=True, interval=400)
        self._temporizador.timeout.connect(self.validar)

        if not self._restaurar_geometria():
            self.resizeDocks([self.dock], [int(self.height() * 0.22)], Qt.Vertical)
        self.dock.show()  # ya no se puede cerrar; si quedó oculto en una sesión anterior, se muestra
        self._actualizar_titulo()
        self._actualizar_acciones()

    # --- construcción de la interfaz ---------------------------------------------------
    def _crear_acciones(self) -> None:
        def accion(texto, atajo=None, funcion=None, tip=None):
            a = QAction(texto, self)
            if atajo:
                a.setShortcut(atajo)
            if funcion:
                a.triggered.connect(funcion)
            if tip:
                a.setStatusTip(tip)
            return a

        self.a_nuevo = accion("&Nuevo anexo…", QKeySequence.New, self.nuevo)
        self.a_abrir = accion("&Abrir…", QKeySequence.Open, self.abrir)
        self.a_guardar = accion("&Guardar", QKeySequence.Save, self.guardar)
        self.a_guardar_como = accion("Guardar &como…", QKeySequence.SaveAs, self.guardar_como)
        self.a_guardar_en = accion("Guardar &en…", "Ctrl+Shift+G", self.guardar_en,
                                   "Guarda una copia en otra ubicación; se sigue trabajando con el archivo actual")
        self.a_exportar = accion("&Exportar para el SRI (ZIP)…", "Ctrl+E", self.exportar,
                                 "Valida el anexo y genera el archivo ATmmaaaa.zip para subir al SRI")
        self.a_excel = accion("Generar E&xcel (XLSX)…", "Ctrl+Shift+X", self.exportar_excel,
                              "Genera un libro de Excel con todos los datos del anexo y una hoja de resumen")
        self.a_salir = accion("&Salir", QKeySequence.Quit, self.close)
        self.a_validar = accion("&Validar anexo", "F5", lambda: self.validar(mostrar=True))
        self.a_importar = accion("&Importar comprobantes electrónicos (XML o PDF)…", "Ctrl+I",
                                 lambda: self.importar_comprobantes(),
                                 "Agrega compras y ventas a partir de los XML o PDF de comprobantes electrónicos")
        self.a_totales = accion("Calcular &total de ventas", None, self.calcular_totales,
                                "Pone en el total de ventas la suma de las bases de ventas")
        self.a_esquema = accion("Importar &esquema del SRI…", None, self.importar_esquema)
        self.a_acerca = accion("&Acerca de", None, self.acerca_de)

        # Sin barra de menús: solo la barra de herramientas. Las acciones que no están en ella
        # se registran en la ventana para que sus atajos de teclado sigan funcionando.
        self.menuBar().setVisible(False)
        for a in (self.a_guardar_como, self.a_salir):
            self.addAction(a)

        tb = self.addToolBar("Principal")
        tb.setObjectName("barra_principal")
        tb.setMovable(False)
        tb.toggleViewAction().setVisible(False)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        for a in (self.a_nuevo, self.a_abrir, self.a_guardar, self.a_guardar_en, None, self.a_importar, self.a_excel,
                  self.a_validar, self.a_exportar):
            if a is None:
                self._espacio(tb, 28)
                tb.addSeparator()
                self._espacio(tb, 28)
            else:
                tb.addAction(a)
        # acciones principales resaltadas: (fondo, fondo al pasar el mouse, al pulsar)
        colores = {self.a_importar: ("black", "#333333", "#555555"),
                   self.a_validar: ("#1565c0", "#1e88e5", "#0d47a1"),    # azul
                   self.a_exportar: ("#2e7d32", "#43a047", "#1b5e20")}   # verde
        for a, (fondo, encima, pulsado) in colores.items():
            tb.widgetForAction(a).setStyleSheet(
                f"QToolButton {{ background: {fondo}; color: white; border-radius: 4px; padding: 4px 10px;"
                f" margin: 2px 3px; }}"
                f"QToolButton:hover {{ background: {encima}; }}"
                f"QToolButton:pressed {{ background: {pulsado}; }}"
                "QToolButton:disabled { background: #9e9e9e; color: #eeeeee; }")
        tb.widgetForAction(self.a_excel).setStyleSheet(
            "QToolButton { background: white; color: black; border: 1px solid #555555; border-radius: 4px;"
            " padding: 3px 10px; margin: 2px 3px; }"
            "QToolButton:hover { background: #eeeeee; }"
            "QToolButton:pressed { background: #dddddd; }"
            "QToolButton:disabled { color: #9e9e9e; border-color: #bdbdbd; }")

    @staticmethod
    def _espacio(tb, ancho: int) -> None:
        hueco = QWidget()
        hueco.setFixedWidth(ancho)
        tb.addWidget(hueco)

    def _crear_bienvenida(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        titulo = QLabel("<h2>Editor del Anexo Transaccional Simplificado (ATS)</h2>"
                        "<p>Cree un anexo nuevo o abra un archivo AT-mmaaaa.xml / ATmmaaaa.zip existente.</p>")
        titulo.setAlignment(Qt.AlignCenter)
        titulo.setWordWrap(True)
        fila = QHBoxLayout()
        fila.addStretch(1)
        for texto, funcion in (("Nuevo anexo", self.nuevo), ("Abrir anexo…", self.abrir)):
            b = QPushButton(texto)
            b.setMinimumWidth(160)
            b.setMinimumHeight(36)
            b.clicked.connect(funcion)
            fila.addWidget(b)
        fila.addStretch(1)
        lay.addWidget(titulo)
        lay.addLayout(fila)
        self.lbl_recientes = QLabel()
        self.lbl_recientes.setAlignment(Qt.AlignCenter)
        self.lbl_recientes.setTextFormat(Qt.RichText)
        self.lbl_recientes.linkActivated.connect(lambda r: self.abrir(r))
        lay.addWidget(self.lbl_recientes)
        lay.addStretch(2)
        self._actualizar_bienvenida()
        return w

    def _actualizar_bienvenida(self) -> None:
        recientes = [r for r in self._recientes() if Path(r).exists()][:5]
        if recientes:
            enlaces = "<br>".join(f"<a href='{r}'>{Path(r).name}</a> <small>({Path(r).parent})</small>" for r in recientes)
            self.lbl_recientes.setText(f"<p><b>Recientes</b><br>{enlaces}</p>")
        else:
            self.lbl_recientes.setText("")

    def _construir_pestanas(self) -> None:
        self.pestanas.clear()
        self.paneles.clear()
        self.formularios.clear()
        raiz = self.doc.raiz
        periodo = self._periodo()

        # Cabecera e informe resumen
        pagina = QWidget()
        lay = QVBoxLayout(pagina)
        self.form_cabecera = FormularioNodo(raiz, self.catalogos, periodo, solo_simples=True)
        self.form_cabecera.cambiado.connect(self._cabecera_cambiada)
        caja = QGroupBox("Datos del informante y del período")
        QVBoxLayout(caja).addWidget(self.form_cabecera)
        lay.addWidget(caja)
        self.caja_resumen = QGroupBox("Resumen del período")
        self.lbl_resumen = QLabel()
        self.lbl_resumen.setTextFormat(Qt.RichText)
        self.lbl_resumen.setWordWrap(True)
        b_total = QPushButton("Usar el total calculado")
        b_total.clicked.connect(self.calcular_totales)
        lr = QVBoxLayout(self.caja_resumen)
        lr.addWidget(self.lbl_resumen)
        fila = QHBoxLayout()
        fila.addWidget(b_total)
        fila.addStretch(1)
        lr.addLayout(fila)
        lay.addWidget(self.caja_resumen)
        lay.addStretch(1)
        self.pestanas.addTab(_desplazable(pagina), "Informante")

        for d in raiz.defn.hijos:
            if d.es_simple:
                continue
            contenedor = raiz.hijo(d.nombre)
            unico = d.hijos[0] if len(d.hijos) == 1 else None
            if contenedor is None:
                contenedor = raiz.agregar(d.nombre, crear_vacio(d))
                if unico is not None and unico.es_repetible:
                    for h in list(contenedor.hijos):
                        contenedor.eliminar(h)
            if unico is not None and unico.es_repetible and not unico.es_simple:
                panel = PanelLista(contenedor, unico, self.catalogos, periodo,
                                   validador=lambda original, copia, c=contenedor: self._validar_registro(c, original, copia))
                panel.modificado.connect(self._al_modificar)
                self.paneles[d.nombre] = panel
                if d.nombre in ("compras", "ventas"):
                    b = QPushButton("Importar comprobantes (XML o PDF)…")
                    b.setToolTip("También puede arrastrar los archivos XML o PDF (o un ZIP o una carpeta) a esta ventana")
                    b.clicked.connect(lambda: self.importar_comprobantes())
                    panel.barra.insertWidget(4, b)
                    panel.vista.marca_agua = (
                        "Arrastra aquí tus compras y retenciones de compras\n(archivos XML o PDF, un ZIP o una carpeta)"
                        if d.nombre == "compras" else
                        "Arrastra aquí tus ventas y retenciones de ventas\n(archivos PDF o XML, un ZIP o una carpeta)")
                self.pestanas.addTab(panel, etiqueta(d.nombre))
            else:
                form = FormularioNodo(contenedor, self.catalogos, periodo)
                form.cambiado.connect(self._al_modificar)
                self.formularios[d.nombre] = form
                self.pestanas.addTab(_desplazable(form), etiqueta(d.nombre))
        self._actualizar_titulos_pestanas()
        self._actualizar_resumen()

    # --- estado ----------------------------------------------------------------------------
    def _periodo(self):
        semestral = self.doc.raiz.texto("regimenMicroempresa") == "SI"
        return rango_periodo(self.doc.anio, self.doc.mes, semestral)

    def _al_modificar(self) -> None:
        self.modificado = True
        self._actualizar_titulo()
        self._actualizar_titulos_pestanas()
        self._actualizar_resumen()
        self._temporizador.start()

    def _cabecera_cambiada(self) -> None:
        periodo = self._periodo()
        for p in self.paneles.values():
            p.periodo = periodo
        self._al_modificar()

    def _actualizar_titulo(self) -> None:
        nombre = self.ruta.name if self.ruta else ("Sin guardar" if self.doc else "")
        marca = " *" if self.modificado else ""
        self.setWindowTitle(f"{nombre}{marca} — Editor ATS" if nombre else "Editor ATS")

    def _actualizar_titulos_pestanas(self) -> None:
        for i in range(self.pestanas.count()):
            w = self.pestanas.widget(i)
            for nombre, panel in self.paneles.items():
                if panel is w:
                    n = len(panel.modelo.filas())
                    self.pestanas.setTabText(i, f"{etiqueta(nombre)} ({n})" if n else etiqueta(nombre))

    def _actualizar_acciones(self) -> None:
        hay = self.doc is not None
        for a in (self.a_guardar, self.a_guardar_como, self.a_guardar_en, self.a_exportar, self.a_excel, self.a_validar, self.a_totales,
                  self.a_importar):
            a.setEnabled(hay)

    def _actualizar_resumen(self) -> None:
        if self.doc is None:
            return
        raiz = self.doc.raiz
        compras = raiz.hijo("compras").lista("detalleCompras") if raiz.hijo("compras") else []
        ventas = raiz.hijo("ventas").lista("detalleVentas") if raiz.hijo("ventas") else []
        def suma(nodos, campo):
            return sum((dec(n.texto(campo)) for n in nodos), Decimal(0))
        total_ventas = total_ventas_de(raiz)
        declarado = raiz.texto("totalVentas") or "0.00"
        coincide = dec(declarado) == total_ventas
        estado = "✔ coincide" if coincide else "<span style='color:#c62828'>✖ no coincide</span>"
        self.lbl_resumen.setText(
            f"<table cellspacing=6>"
            f"<tr><td><b>Compras</b></td><td>{len(compras)} registro(s)</td>"
            f"<td>Base gravada: {suma(compras, 'baseImpGrav'):,.2f}</td><td>Base 0%: {suma(compras, 'baseImponible'):,.2f}</td>"
            f"<td>IVA: {suma(compras, 'montoIva'):,.2f}</td></tr>"
            f"<tr><td><b>Ventas</b></td><td>{len(ventas)} registro(s)</td>"
            f"<td>Base gravada: {suma(ventas, 'baseImpGrav'):,.2f}</td><td>Base 0%: {suma(ventas, 'baseImponible'):,.2f}</td>"
            f"<td>IVA: {suma(ventas, 'montoIva'):,.2f}</td></tr>"
            f"<tr><td><b>Total ventas</b></td><td colspan=4>calculado {total_ventas:,.2f} · declarado {dec(declarado):,.2f} · {estado}"
            f" <small>(como DIMM: solo ventas con emisión F; las notas de crédito restan)</small></td></tr></table>")
        self._total_calculado = total_ventas

    # --- validación -------------------------------------------------------------------------
    def validar(self, mostrar: bool = False) -> None:
        if self.doc is None:
            return
        self.mensajes = validar_documento(self.doc, self.catalogos)
        self.panel_mensajes.poner(self.mensajes)
        for panel in self.paneles.values():
            panel.poner_mensajes(self.mensajes)
        errores = sum(1 for m in self.mensajes if m.es_error)
        avisos = len(self.mensajes) - errores
        self.lbl_estado.setText(f"Errores: {errores}   Advertencias: {avisos}")
        if mostrar:
            self.dock.show()
            if not self.mensajes:
                self.statusBar().showMessage("El anexo es válido.", 5000)

    def _validar_registro(self, contenedor: Nodo, original: Nodo | None, copia: Nodo):
        """Valida un registro en el contexto del documento sin modificarlo."""
        if original is not None:
            contenedor.reemplazar(original, copia)
        else:
            contenedor.agregar(copia.nombre, copia)
        try:
            base = copia.ruta()
            mensajes = validar_documento(self.doc, self.catalogos, con_xsd=False)
            propios = [m for m in mensajes if m.ruta == base or m.ruta.startswith(base + "/")]
        finally:
            if original is not None:
                contenedor.reemplazar(copia, original)
            else:
                contenedor.eliminar(copia)
            copia.padre = None
        return propios, base

    def navegar(self, m: Mensaje) -> None:
        partes = [p for p in m.ruta.strip("/").split("/") if p]
        if len(partes) <= 2:
            self.pestanas.setCurrentIndex(0)
            if len(partes) == 2 and self.form_cabecera is not None:
                nombre = partes[1].split("[")[0]
                if not self.form_cabecera.enfocar(nombre):
                    self._ir_a_pestana(nombre)
            return
        seccion = partes[1].split("[")[0]
        panel = self.paneles.get(seccion)
        if panel is None:
            self._ir_a_pestana(seccion)
            form = self.formularios.get(seccion)
            if form is not None:
                form.enfocar("/".join(partes[2:]))
            return
        self.pestanas.setCurrentWidget(panel)
        mt = re.fullmatch(r"[^\[]+(?:\[(\d+)\])?", partes[2])
        fila = int(mt.group(1)) - 1 if mt and mt.group(1) else 0
        if fila >= len(panel.modelo.filas()):
            return
        panel.seleccionar(fila)
        resto = "/".join(partes[3:])
        panel.editar(fila, enfocar=resto or "/")

    def _ir_a_pestana(self, nombre: str) -> None:
        objetivo = self.paneles.get(nombre) or self.formularios.get(nombre)
        for i in range(self.pestanas.count()):
            w = self.pestanas.widget(i)
            if objetivo is not None and (w is objetivo or w.isAncestorOf(objetivo)):
                self.pestanas.setCurrentIndex(i)
                return

    # --- archivo ---------------------------------------------------------------------------
    def _confirmar_descartar(self) -> bool:
        if not self.modificado:
            return True
        caja = QMessageBox(QMessageBox.Question, "Cambios sin guardar",
                           "El anexo tiene cambios sin guardar. ¿Desea guardarlos?", parent=self)
        b_no = caja.addButton("No guardar", QMessageBox.ActionRole)
        b_cancelar = caja.addButton("Cancelar", QMessageBox.ActionRole)
        b_guardar = caja.addButton("Guardar", QMessageBox.ActionRole)
        estilo = "QPushButton {{ background: {0}; color: {1}; border: 1px solid {2}; border-radius: 4px; " \
                 "padding: 6px 16px; min-width: 90px; }} QPushButton:hover {{ border: 2px solid {2}; }}"
        b_no.setStyleSheet(estilo.format("#f4a6a6", "black", "#d77a7a"))       # rojo pastel
        b_cancelar.setStyleSheet(estilo.format("black", "white", "#555555"))
        b_guardar.setStyleSheet(estilo.format("#8fd19e", "black", "#4caf68"))  # verde
        caja.setDefaultButton(b_guardar)
        caja.setEscapeButton(b_cancelar)
        caja.exec()
        if caja.clickedButton() is b_guardar:
            return self.guardar()
        return caja.clickedButton() is b_no

    def poner_documento(self, doc: Documento, ruta: Path | None) -> None:
        self.doc = doc
        self._ventas_pendientes: list[str] = []
        self.ruta = ruta
        self.modificado = False
        self._construir_pestanas()
        self.pila.setCurrentIndex(1)
        self._actualizar_titulo()
        self._actualizar_acciones()
        self.validar()
        if doc.avisos_carga:
            QMessageBox.warning(self, "Aviso", "El archivo contiene elementos que no están en el esquema:\n\n"
                                + "\n".join(doc.avisos_carga[:10]))

    def nuevo(self) -> None:
        if not self._confirmar_descartar():
            return
        dlg = DialogoNuevo(self)
        if dlg.exec() != DialogoNuevo.Accepted:
            return
        doc = Documento(self.esquema)
        raiz = doc.raiz
        raiz.poner("TipoIDInformante", "R")
        raiz.poner("codigoOperativo", "IVA")
        for campo, valor in dlg.datos.items():
            if valor and raiz.defn.hijo(campo) is not None:
                raiz.poner(campo, valor)
        if raiz.defn.hijo("totalVentas") is not None:
            raiz.poner("totalVentas", "0.00")
        self.poner_documento(doc, None)
        self.modificado = True
        self._actualizar_titulo()

    def abrir(self, ruta: str | None = None) -> None:
        if not self._confirmar_descartar():
            return
        if not ruta:
            carpeta = QSettings().value("ultima_carpeta", str(Path.home()))
            ruta, _ = QFileDialog.getOpenFileName(self, "Abrir anexo", carpeta, FILTRO_ABRIR)
            if not ruta:
                return
        try:
            doc = Documento.desde_archivo(self.esquema, ruta)
        except Exception as e:  # noqa: BLE001 - se informa al usuario
            QMessageBox.critical(self, "No se pudo abrir", f"No se pudo leer el archivo:\n{ruta}\n\n{e}")
            return
        p = Path(ruta)
        QSettings().setValue("ultima_carpeta", str(p.parent))
        self._agregar_reciente(p)
        # un ZIP se abre pero se guarda como XML
        self.poner_documento(doc, p if p.suffix.lower() == ".xml" else None)

    def guardar(self) -> bool:
        if self.doc is None:
            return False
        if self.ruta is None:
            return self.guardar_como()
        return self._escribir(self.ruta)

    def guardar_como(self) -> bool:
        if self.doc is None:
            return False
        carpeta = Path(QSettings().value("ultima_carpeta", str(Path.home())))
        ruta, _ = QFileDialog.getSaveFileName(self, "Guardar anexo", str(carpeta / self.doc.nombre_sugerido(".xml")),
                                              "XML (*.xml)")
        if not ruta:
            return False
        p = Path(ruta)
        if p.suffix.lower() != ".xml":
            p = p.with_suffix(".xml")
        return self._escribir(p)

    def guardar_en(self) -> None:
        """Guarda una copia en otra carpeta sin cambiar el archivo con el que se trabaja."""
        if self.doc is None:
            return
        cfg = QSettings()
        carpeta = Path(cfg.value("guardar_en/carpeta", cfg.value("ultima_carpeta", str(Path.home()))))
        nombre = self.ruta.name if self.ruta else self.doc.nombre_sugerido(".xml")
        ruta, filtro = QFileDialog.getSaveFileName(self, "Guardar una copia en…", str(carpeta / nombre),
                                                   "Anexo XML (*.xml);;ZIP para el SRI (*.zip)")
        if not ruta:
            return
        p = Path(ruta)
        if p.suffix.lower() not in (".xml", ".zip"):
            p = p.with_suffix(".zip" if "zip" in filtro.lower() else ".xml")
        if self.ruta is not None and p.resolve() == self.ruta.resolve():
            self.guardar()
            return
        try:
            if p.suffix.lower() == ".zip":
                self.doc.guardar_zip(p)
            else:
                self.doc.guardar_xml(p)
        except OSError as e:
            QMessageBox.critical(self, "Error al guardar", str(e))
            return
        cfg.setValue("guardar_en/carpeta", str(p.parent))
        actual = f" Sigue trabajando en {self.ruta}." if self.ruta else ""
        self.statusBar().showMessage(f"Copia guardada en {p}.{actual}", 8000)

    def _escribir(self, ruta: Path) -> bool:
        try:
            self.doc.guardar_xml(ruta)
        except OSError as e:
            QMessageBox.critical(self, "Error al guardar", str(e))
            return False
        self.ruta = ruta
        self.modificado = False
        registro_ventas.registrar(self._clave_registro(), self._ventas_pendientes)
        self._ventas_pendientes = []
        QSettings().setValue("ultima_carpeta", str(ruta.parent))
        self._agregar_reciente(ruta)
        self._actualizar_titulo()
        self.statusBar().showMessage(f"Guardado en {ruta}", 5000)
        return True

    def exportar(self) -> None:
        if self.doc is None:
            return
        self.validar(mostrar=True)
        errores = [m for m in self.mensajes if m.es_error]
        if errores:
            r = QMessageBox.warning(
                self, "El anexo tiene errores",
                f"El anexo tiene {len(errores)} error(es) (vea el panel de validación). El SRI probablemente "
                "rechazará el archivo.\n\n¿Exportar de todos modos?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        carpeta = self.ruta.parent if self.ruta else Path(QSettings().value("ultima_carpeta", str(Path.home())))
        ruta, _ = QFileDialog.getSaveFileName(self, "Exportar para el SRI", str(carpeta / self.doc.nombre_sugerido(".zip")),
                                              "Archivo ZIP (*.zip)")
        if not ruta:
            return
        p = Path(ruta)
        if p.suffix.lower() != ".zip":
            p = p.with_suffix(".zip")
        try:
            self.doc.guardar_zip(p)
        except OSError as e:
            QMessageBox.critical(self, "Error al exportar", str(e))
            return
        QMessageBox.information(self, "Anexo exportado",
                                f"Se generó {p.name} con el archivo {self.doc.nombre_sugerido('.xml')} adentro.\n\n"
                                "Súbalo en el portal del SRI (SRI en línea → Anexos).")

    def exportar_excel(self) -> None:
        if self.doc is None:
            return
        carpeta = self.ruta.parent if self.ruta else Path(QSettings().value("ultima_carpeta", str(Path.home())))
        nombre = self.doc.nombre_sugerido(".xml").removesuffix(".xml") + ".xlsx"
        ruta, _ = QFileDialog.getSaveFileName(self, "Generar Excel del anexo", str(carpeta / nombre),
                                              "Libro de Excel (*.xlsx)")
        if not ruta:
            return
        p = Path(ruta)
        if p.suffix.lower() != ".xlsx":
            p = p.with_suffix(".xlsx")
        from ..excel import exportar_xlsx

        try:
            exportar_xlsx(self.doc, p, self.catalogos)
        except PermissionError:
            QMessageBox.critical(self, "No se pudo guardar",
                                 f"No se pudo escribir {p.name}. ¿Está abierto en otro programa? Ciérrelo e intente "
                                 "de nuevo.")
            return
        except OSError as e:
            QMessageBox.critical(self, "Error al generar el Excel", str(e))
            return
        caja = QMessageBox(QMessageBox.Information, "Excel generado",
                           f"Se generó {p.name} con una hoja de resumen y una hoja por cada tabla del anexo.",
                           parent=self)
        b_abrir = caja.addButton("Abrir el Excel", QMessageBox.AcceptRole)
        caja.addButton("Cerrar", QMessageBox.RejectRole)
        caja.exec()
        if caja.clickedButton() is b_abrir:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def importar_comprobantes(self, rutas: list[Path] | None = None) -> None:
        if self.doc is None:
            QMessageBox.information(self, "Importar comprobantes",
                                    "Primero cree un anexo nuevo o abra uno existente; luego arrastre los XML de sus facturas.")
            return
        if not rutas:
            carpeta = QSettings().value("importar/carpeta", str(Path.home()))
            elegidos, _ = QFileDialog.getOpenFileNames(self, "Comprobantes electrónicos", carpeta,
                                                       "Comprobantes (*.xml *.zip *.pdf);;Todos (*)")
            if not elegidos:
                return
            rutas = [Path(e) for e in elegidos]
            QSettings().setValue("importar/carpeta", str(rutas[0].parent))
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            leidos = comprobantes.leer_rutas(rutas)
        finally:
            QGuiApplication.restoreOverrideCursor()
        if not leidos:
            QMessageBox.information(self, "Importar comprobantes", "No se encontraron archivos XML.")
            return
        ruc = self.doc.raiz.texto("IdInformante")
        nombres = {}
        for c in leidos:
            if isinstance(c, comprobantes.Comprobante):
                if comprobantes.es_venta(c, ruc):
                    nombres[c.id_contraparte] = c.razon_contraparte
                else:
                    nombres[c.ruc_proveedor] = c.razon_proveedor
            elif isinstance(c, retenciones.Retencion):
                if c.id_retenido == ruc:
                    nombres.setdefault(c.ruc_agente, c.razon_agente)
                else:
                    nombres.setdefault(c.id_retenido, c.razon_retenido)
        proveedores.recordar(nombres)
        dlg = DialogoImportarComprobantes(self.doc, leidos, self.catalogos, self._periodo(), self,
                                          ventas_importadas=self._ventas_importadas())
        if dlg.exec() != DialogoImportarComprobantes.Accepted:
            return
        res = comprobantes.importar(self.doc, dlg.propuestas)
        res_ret = retenciones.aplicar(self.doc, dlg.prop_ret)
        for p in dlg.prop_ret:
            if p.seleccionado and p.destino == "compras":
                retenciones.recordar_codigos(p.retencion)
        self._ventas_pendientes += res.claves_ventas + res_ret.claves_ventas
        raiz = self.doc.raiz
        for nombre, panel in self.paneles.items():
            if raiz.hijo(nombre) is not None:
                panel.poner_contenedor(raiz.hijo(nombre))
        if self.form_cabecera is not None and "totalVentas" in self.form_cabecera.celdas:
            self.form_cabecera.celdas["totalVentas"].campo.poner_valor(raiz.texto("totalVentas"))
        self._al_modificar()
        self.validar()
        if res.compras or res_ret.compras:
            destino, primero = "compras", (res.compras or res_ret.compras)[0]
        else:
            destino, primero = "ventas", (res.ventas or res_ret.ventas or [None])[0]
        panel = self.paneles.get(destino)
        if panel is not None and primero is not None:
            self.pestanas.setCurrentWidget(panel)
            panel.seleccionar(panel.modelo.filas().index(primero))
        partes = []
        if res.compras:
            partes.append(f"{len(res.compras)} compra(s)")
        if res.claves_ventas:
            partes.append(f"{len(res.claves_ventas)} venta(s) en {len(res.ventas)} registro(s) de cliente")
        n_ret = len(res_ret.compras) + len(res_ret.claves_ventas)
        if n_ret:
            partes.append(f"{n_ret} retención(es)")
        self.statusBar().showMessage("Se agregaron " + ", ".join(partes) + ".", 10000)
        if res_ret.no_aplicadas:
            QMessageBox.warning(self, "Retenciones no registradas",
                                "Estas retenciones no se pudieron registrar porque no se encontró el comprobante que "
                                "sustentan (¿desmarcó la factura?):\n\n" + "\n".join(res_ret.no_aplicadas))

    def _clave_registro(self) -> str:
        r = self.doc.raiz
        return registro_ventas.clave_anexo(r.texto("IdInformante"), r.texto("Anio"), r.texto("Mes"))

    def _ventas_importadas(self) -> set[str]:
        return registro_ventas.importadas(self._clave_registro()) | set(self._ventas_pendientes)

    def calcular_totales(self) -> None:
        if self.doc is None:
            return
        self._actualizar_resumen()
        total = f"{self._total_calculado:.2f}"
        raiz = self.doc.raiz
        raiz.poner("totalVentas", total)
        if self.form_cabecera is not None and "totalVentas" in self.form_cabecera.celdas:
            self.form_cabecera.celdas["totalVentas"].campo.poner_valor(total)
        nota = ""
        ve = raiz.hijo("ventasEstablecimiento")
        ests = ve.lista("ventaEst") if ve else []
        if len(ests) == 1:
            ests[0].poner("ventasEstab", total)
            if "ventasEstablecimiento" in self.paneles:
                self.paneles["ventasEstablecimiento"].poner_contenedor(ve)
            nota = " y en las ventas del establecimiento"
        self.statusBar().showMessage(f"Total de ventas actualizado a {total}{nota}.", 6000)
        self._al_modificar()

    def importar_esquema(self) -> None:
        dlg = DialogoEsquema(self)
        if dlg.exec() and dlg.importado:
            QMessageBox.information(self, "Esquema", "Reinicie la aplicación para usar el nuevo esquema.")

    def acerca_de(self) -> None:
        QMessageBox.about(self, "Acerca de",
                          f"<b>Editor ATS</b> {__version__}<br>Editor y validador del Anexo Transaccional "
                          "Simplificado del SRI de Ecuador.<br><br>Esquema en uso:<br><code>"
                          f"{self.esquema.ruta}</code><br><br>Las reglas se basan en la ficha técnica pública del ATS. "
                          "Esta aplicación no es un producto oficial del SRI.")

    # --- recientes ---------------------------------------------------------------------------
    def _recientes(self) -> list[str]:
        v = QSettings().value("recientes", [])
        return [v] if isinstance(v, str) else list(v or [])

    def _agregar_reciente(self, ruta: Path) -> None:
        lista = [str(ruta)] + [r for r in self._recientes() if r != str(ruta)]
        QSettings().setValue("recientes", lista[:MAX_RECIENTES])
        self._actualizar_bienvenida()

    # --- ventana -----------------------------------------------------------------------------
    def _restaurar_geometria(self) -> bool:
        cfg = QSettings()
        geo = cfg.value("ventana/geometria")
        if isinstance(geo, QByteArray) and self.restoreGeometry(geo):
            estado = cfg.value("ventana/estado")
            if isinstance(estado, QByteArray):
                self.restoreState(estado)
            return True
        disp = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(int(disp.width() * 0.85), int(disp.height() * 0.85))
        self.move(disp.center() - self.rect().center())
        return False

    def closeEvent(self, evento) -> None:
        if not self._confirmar_descartar():
            evento.ignore()
            return
        cfg = QSettings()
        cfg.setValue("ventana/geometria", self.saveGeometry())
        cfg.setValue("ventana/estado", self.saveState())
        evento.accept()

    def dragEnterEvent(self, evento) -> None:
        rutas = [Path(u.toLocalFile()) for u in evento.mimeData().urls() if u.isLocalFile()]
        if rutas and all(r.is_dir() or r.suffix.lower() in (".xml", ".zip", ".pdf") for r in rutas):
            evento.acceptProposedAction()

    def dropEvent(self, evento) -> None:
        rutas = [Path(u.toLocalFile()) for u in evento.mimeData().urls() if u.isLocalFile()]
        if not rutas:
            return
        evento.acceptProposedAction()
        if len(rutas) == 1 and rutas[0].is_file() and comprobantes.parece_anexo(rutas[0]):
            self.abrir(str(rutas[0]))
        else:
            # se procesa después de soltar para no bloquear al gestor de archivos
            QTimer.singleShot(0, lambda: self.importar_comprobantes(rutas))


def _desplazable(w: QWidget) -> QScrollArea:
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setFrameShape(QFrame.NoFrame)
    contenedor = QWidget()
    lay = QVBoxLayout(contenedor)
    lay.addWidget(w)
    area.setWidget(contenedor)
    return area
