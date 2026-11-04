"""Vista previa e importación de comprobantes electrónicos (compras, ventas y retenciones)."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings, Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QStyle, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..catalogos import Catalogos
from ..comprobantes import AVISO, OK, ArchivoNoLeido, Comprobante, Propuesta, analizar
from ..documento import Documento
from ..retenciones import PropuestaRetencion, Retencion
from ..retenciones import analizar as analizar_retenciones

COLUMNAS = ["", "Estado", "Va a", "Proveedor / Cliente", "Tipo", "Número", "Emisión", "Sustento", "Base gravada",
            "Base 0%", "IVA", "Total", "Observaciones", "Archivo"]
(C_SEL, C_ESTADO, C_DEST, C_PROV, C_TIPO, C_NUM, C_FECHA, C_SUST, C_GRAV, C_CERO, C_IVA, C_TOTAL, C_OBS,
 C_ARCH) = range(14)


class DialogoImportarComprobantes(QDialog):
    def __init__(self, doc: Documento, leidos: list[Comprobante | ArchivoNoLeido], catalogos: Catalogos, periodo,
                 parent=None, ventas_importadas: set[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Importar comprobantes electrónicos")
        self.ventas_importadas = ventas_importadas or set()
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setSizeGripEnabled(True)
        self.doc = doc
        self.catalogos = catalogos
        self.comprobantes = [x for x in leidos if isinstance(x, Comprobante)]
        self.retenciones = [x for x in leidos if isinstance(x, Retencion)]
        self.no_leidos = [x for x in leidos if isinstance(x, ArchivoNoLeido)]
        tabla_sustento = catalogos.tablas.get("t5_sustento")
        self.sustentos = [(f.codigo, f.descripcion) for f in (tabla_sustento.vigentes(*periodo) if tabla_sustento else [])]

        cfg = QSettings()
        self.defecto = QComboBox()
        for codigo, desc in self.sustentos:
            self.defecto.addItem(f"{codigo} — {desc}", codigo)
        i = self.defecto.findData(cfg.value("importar/sustento", "01"))
        self.defecto.setCurrentIndex(max(i, 0))
        self.defecto.setToolTip("Se usa para los proveedores que todavía no tienen compras en el anexo. "
                                "Para los demás se repite el sustento de sus compras anteriores.")
        self.defecto.currentIndexChanged.connect(self._reanalizar)

        self.resumen = QLabel()
        self.resumen.setWordWrap(True)
        self.tabla = QTableWidget(0, len(COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(COLUMNAS)
        self.tabla.verticalHeader().hide()
        self.tabla.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabla.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        cab = self.tabla.horizontalHeader()
        cab.setSectionResizeMode(QHeaderView.Interactive)
        cab.setStretchLastSection(True)
        self.tabla.itemChanged.connect(self._marca_cambiada)

        b_todos = QPushButton("Marcar todos")
        b_ninguno = QPushButton("Desmarcar todos")
        b_todos.clicked.connect(lambda: self._marcar_todos(True))
        b_ninguno.clicked.connect(lambda: self._marcar_todos(False))
        fila = QHBoxLayout()
        fila.addWidget(QLabel("Sustento tributario para proveedores nuevos:"))
        fila.addWidget(self.defecto, 1)
        fila.addSpacing(20)
        fila.addWidget(b_todos)
        fila.addWidget(b_ninguno)

        self.botones = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.botones.button(QDialogButtonBox.Cancel).setText("Cancelar")
        self.botones.accepted.connect(self._aceptar)
        self.botones.rejected.connect(self.reject)

        ayuda = QLabel("Las facturas emitidas a su RUC van a Compras y las emitidas por su RUC van a Ventas (agrupadas "
                       "por cliente). Las retenciones que le hicieron sus clientes se suman en Ventas; las que usted emitió "
                       "se registran en la compra correspondiente. Revise el sustento tributario de cada compra.")
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet("color: palette(mid);")

        lay = QVBoxLayout(self)
        lay.addWidget(self.resumen)
        lay.addLayout(fila)
        lay.addWidget(self.tabla, 1)
        lay.addWidget(ayuda)
        lay.addWidget(self.botones)

        geo = cfg.value("dialogo/importar_comprobantes")
        if not (isinstance(geo, QByteArray) and self.restoreGeometry(geo)):
            disp = (parent.screen() if parent else QGuiApplication.primaryScreen()).availableGeometry()
            self.resize(min(int(disp.width() * 0.9), 1500), min(int(disp.height() * 0.8), 800))
        self._reanalizar()

    # ------------------------------------------------------------------------------------
    def _reanalizar(self) -> None:
        self.propuestas: list[Propuesta] = analizar(self.doc, self.comprobantes, self.defecto.currentData() or "01",
                                                    ventas_importadas=self.ventas_importadas)
        self.prop_ret: list[PropuestaRetencion] = analizar_retenciones(self.doc, self.retenciones, self.propuestas,
                                                                       self.ventas_importadas)
        self.filas = list(self.propuestas) + list(self.prop_ret)
        self._llenar()

    def _llenar(self) -> None:
        estilo = QApplication.style()
        iconos = {OK: estilo.standardIcon(QStyle.SP_DialogApplyButton),
                  AVISO: estilo.standardIcon(QStyle.SP_MessageBoxWarning)}
        icono_omitir = estilo.standardIcon(QStyle.SP_MessageBoxCritical)
        icono_registrado = estilo.standardIcon(QStyle.SP_MessageBoxInformation)
        textos = {OK: "Listo", AVISO: "Revisar"}
        self.tabla.blockSignals(True)
        self.tabla.setRowCount(len(self.filas) + len(self.no_leidos))
        for fila, p in enumerate(self.propuestas):
            c = p.comprobante
            marca = QTableWidgetItem()
            if p.estado in (OK, AVISO):
                marca.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                marca.setCheckState(Qt.Checked if p.seleccionado else Qt.Unchecked)
            else:
                marca.setFlags(Qt.NoItemFlags)
            marca.setData(Qt.UserRole, fila)
            self.tabla.setItem(fila, C_SEL, marca)
            if p.ya_registrado:
                estado = QTableWidgetItem(icono_registrado, "Ya importada" if p.destino == "ventas" else "Ya está en el anexo")
            else:
                estado = QTableWidgetItem(iconos.get(p.estado, icono_omitir), textos.get(p.estado, "No se importa"))
            self.tabla.setItem(fila, C_ESTADO, estado)
            self.tabla.setItem(fila, C_DEST, QTableWidgetItem("Ventas" if p.destino == "ventas" else "Compras"))
            if p.destino == "ventas":
                self.tabla.setItem(fila, C_PROV, QTableWidgetItem(f"{c.id_contraparte}  {c.razon_contraparte}"))
            else:
                self.tabla.setItem(fila, C_PROV, QTableWidgetItem(f"{c.ruc_proveedor}  {c.razon_proveedor}"))
            self.tabla.setItem(fila, C_TIPO, QTableWidgetItem(c.tipo_nombre))
            self.tabla.setItem(fila, C_NUM, QTableWidgetItem(c.numero))
            self.tabla.setItem(fila, C_FECHA, QTableWidgetItem(f"{c.fecha_emision:%d/%m/%Y}" if c.fecha_emision else ""))
            for col, valor in ((C_GRAV, c.base_gravada), (C_CERO, c.base_cero + c.base_no_objeto + c.base_exenta),
                               (C_IVA, c.iva), (C_TOTAL, c.total)):
                item = QTableWidgetItem(f"{valor:,.2f}")
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla.setItem(fila, col, item)
            obs = QTableWidgetItem("; ".join(p.notas))
            obs.setToolTip("\n".join(p.notas))
            self.tabla.setItem(fila, C_OBS, obs)
            self.tabla.setItem(fila, C_ARCH, QTableWidgetItem(c.archivo))
            if p.estado in (OK, AVISO) and p.destino == "compras":
                combo = QComboBox()
                for codigo, desc in self.sustentos:
                    combo.addItem(codigo, codigo)
                    combo.setItemData(combo.count() - 1, desc, Qt.ToolTipRole)
                i = combo.findData(p.sustento)
                if i < 0:
                    combo.addItem(p.sustento, p.sustento)
                    i = combo.count() - 1
                combo.setCurrentIndex(i)
                combo.setToolTip(combo.itemData(i, Qt.ToolTipRole) or "")
                combo.currentIndexChanged.connect(lambda _i, p=p, combo=combo: self._sustento(p, combo))
                self.tabla.setCellWidget(fila, C_SUST, combo)
            else:
                self.tabla.removeCellWidget(fila, C_SUST)
                self.tabla.setItem(fila, C_SUST, QTableWidgetItem(""))
        for j, p in enumerate(self.prop_ret):
            self._fila_retencion(len(self.propuestas) + j, p, iconos, textos, icono_omitir, icono_registrado)
        base = len(self.filas)
        for j, nl in enumerate(self.no_leidos):
            fila = base + j
            marca = QTableWidgetItem()
            marca.setFlags(Qt.NoItemFlags)
            self.tabla.setItem(fila, C_SEL, marca)
            self.tabla.setItem(fila, C_ESTADO, QTableWidgetItem(icono_omitir, "No se pudo leer"))
            obs = QTableWidgetItem(nl.motivo)
            obs.setToolTip(nl.motivo)
            self.tabla.setItem(fila, C_OBS, obs)
            self.tabla.setItem(fila, C_ARCH, QTableWidgetItem(nl.archivo))
            for col in (C_DEST, C_PROV, C_TIPO, C_NUM, C_FECHA, C_SUST, C_GRAV, C_CERO, C_IVA, C_TOTAL):
                self.tabla.setItem(fila, col, QTableWidgetItem(""))
        self.tabla.blockSignals(False)
        self.tabla.resizeColumnsToContents()
        for col in (C_PROV, C_OBS):
            self.tabla.setColumnWidth(col, min(self.tabla.columnWidth(col), 340))
        self._actualizar_resumen()

    def _fila_retencion(self, fila: int, p: PropuestaRetencion, iconos, textos, icono_omitir, icono_registrado) -> None:
        ret = p.retencion
        marca = QTableWidgetItem()
        if p.estado in (OK, AVISO):
            marca.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            marca.setCheckState(Qt.Checked if p.seleccionado else Qt.Unchecked)
        else:
            marca.setFlags(Qt.NoItemFlags)
        marca.setData(Qt.UserRole, fila)
        self.tabla.setItem(fila, C_SEL, marca)
        if p.ya_registrado:
            estado = QTableWidgetItem(icono_registrado, "Ya importada")
        else:
            estado = QTableWidgetItem(iconos.get(p.estado, icono_omitir), textos.get(p.estado, "No se importa"))
        self.tabla.setItem(fila, C_ESTADO, estado)
        if p.destino == "ventas":
            self.tabla.setItem(fila, C_DEST, QTableWidgetItem("Ventas (retención)"))
            self.tabla.setItem(fila, C_PROV, QTableWidgetItem(f"{ret.ruc_agente}  {ret.razon_agente}"))
        else:
            self.tabla.setItem(fila, C_DEST, QTableWidgetItem("Compras (retención)"))
            self.tabla.setItem(fila, C_PROV, QTableWidgetItem(f"{ret.id_retenido}  {ret.razon_retenido}"))
        self.tabla.setItem(fila, C_TIPO, QTableWidgetItem("Retención" + (" (PDF)" if ret.origen == "pdf" else "")))
        self.tabla.setItem(fila, C_NUM, QTableWidgetItem(ret.numero))
        self.tabla.setItem(fila, C_FECHA, QTableWidgetItem(f"{ret.fecha_emision:%d/%m/%Y}" if ret.fecha_emision else ""))
        for col in (C_SUST, C_GRAV, C_CERO):
            self.tabla.removeCellWidget(fila, col)
            self.tabla.setItem(fila, col, QTableWidgetItem(""))
        for col, valor in ((C_IVA, ret.total_iva), (C_TOTAL, ret.total)):
            item = QTableWidgetItem(f"{valor:,.2f}")
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tabla.setItem(fila, col, item)
        detalle = f"Ret. IVA {ret.total_iva:,.2f} · Ret. renta {ret.total_renta:,.2f} → {p.objetivo}"
        notas = p.notas + ([detalle] if p.estado != "omitir" else [])
        obs = QTableWidgetItem("; ".join(notas))
        obs.setToolTip("\n".join(notas))
        self.tabla.setItem(fila, C_OBS, obs)
        self.tabla.setItem(fila, C_ARCH, QTableWidgetItem(ret.archivo))

    def _diagnostico(self) -> str:
        """Explica la causa cuando la mayoría de comprobantes no coincide con el anexo."""
        from collections import Counter

        comps = [p.comprobante for p in self.propuestas if not p.ya_registrado and p.destino == "compras"]
        if not comps:
            return ""
        raiz = self.doc.raiz
        ruc = raiz.texto("IdInformante")
        destinos = Counter(c.ruc_emisor if c.es_liquidacion else c.id_contraparte for c in comps)
        otro, cuantos = destinos.most_common(1)[0]
        if ruc and otro != ruc and cuantos * 2 > len(comps):
            nombre = next((c.razon_contraparte for c in comps if c.id_contraparte == otro), "")
            return (f"{cuantos} de {len(comps)} comprobantes están a nombre de {otro} {nombre}, pero este anexo es del "
                    f"RUC {ruc}. Si son de esa empresa, cree el anexo con el RUC {otro} (Archivo → Nuevo anexo).")
        meses = Counter((c.fecha_emision.year, c.fecha_emision.month) for c in comps if c.fecha_emision)
        if meses and self.doc.anio and self.doc.mes:
            (anio, mes), cuantos = meses.most_common(1)[0]
            if (anio, mes) != (self.doc.anio, self.doc.mes) and cuantos * 2 > len(comps):
                return (f"La mayoría de comprobantes son de {mes:02d}/{anio}, pero el anexo es del período "
                        f"{self.doc.mes:02d}/{self.doc.anio}. Revise el mes y año en la pestaña «Informante».")
        return ""

    def _sustento(self, p: Propuesta, combo: QComboBox) -> None:
        p.sustento = combo.currentData()
        combo.setToolTip(combo.itemData(combo.currentIndex(), Qt.ToolTipRole) or "")

    def _marca_cambiada(self, item: QTableWidgetItem) -> None:
        if item.column() != C_SEL or item.data(Qt.UserRole) is None:
            return
        self.filas[item.data(Qt.UserRole)].seleccionado = item.checkState() == Qt.Checked
        self._actualizar_resumen()

    def _marcar_todos(self, valor: bool) -> None:
        for fila, p in enumerate(self.filas):
            item = self.tabla.item(fila, C_SEL)
            if item is not None and item.flags() & Qt.ItemIsUserCheckable:
                item.setCheckState(Qt.Checked if valor else Qt.Unchecked)

    def _actualizar_resumen(self) -> None:
        listos = sum(1 for p in self.filas if p.estado == OK)
        revisar = sum(1 for p in self.filas if p.estado == AVISO and not p.ya_registrado)
        registrados = sum(1 for p in self.filas if p.ya_registrado)
        omitidos = len(self.filas) - listos - revisar - registrados + len(self.no_leidos)
        elegidos = sum(1 for p in self.filas if p.seleccionado)
        compras = sum(1 for p in self.propuestas if p.seleccionado and p.destino == "compras")
        ventas = sum(1 for p in self.propuestas if p.seleccionado and p.destino == "ventas")
        n_ret = sum(1 for p in self.prop_ret if p.seleccionado)
        partes = [f"{listos} listo(s)", f"{revisar} para revisar"]
        if registrados:
            partes.append(f"{registrados} que ya están en el anexo")
        partes.append(f"{omitidos} que no se importarán (vea «Observaciones»)")
        self.resumen.setText(f"<b>{len(self.filas) + len(self.no_leidos)} archivo(s)</b>: " + ", ".join(partes) + ".")
        aviso = self._diagnostico()
        if aviso:
            self.resumen.setText(self.resumen.text() + f"<br><span style='color:#c62828'><b>⚠ {aviso}</b></span>")
        ok = self.botones.button(QDialogButtonBox.Ok)
        textos = [t for t in (f"{compras} compra(s)" if compras else "", f"{ventas} venta(s)" if ventas else "",
                              f"{n_ret} retención(es)" if n_ret else "") if t]
        ok.setText("Agregar " + ", ".join(textos) if textos else "Agregar")
        ok.setEnabled(elegidos > 0)

    def _aceptar(self) -> None:
        QSettings().setValue("importar/sustento", self.defecto.currentData())
        self.accept()

    def done(self, resultado: int) -> None:
        QSettings().setValue("dialogo/importar_comprobantes", self.saveGeometry())
        super().done(resultado)
