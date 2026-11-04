# Editor ATS

Editor y validador del **Anexo Transaccional Simplificado (ATS)** del SRI de Ecuador.
Funciona en **Linux, Windows y macOS** (Python + Qt). Es independiente de DIMM: no hace
falta tenerlo instalado. Trae incluido el esquema oficial `at.xsd` del ATS.

> No es un producto oficial del SRI. Revise siempre el anexo antes de presentarlo.

## Qué hace

- Abre anexos existentes (`AT-mmaaaa.xml` o `ATmmaaaa.zip`) y los vuelve a guardar sin
  alterar nada que no se haya modificado (el archivo queda idéntico byte por byte).
- Crea anexos nuevos y permite agregar, editar, duplicar y eliminar compras, ventas,
  ventas por establecimiento, exportaciones, anulados, etc.
- Genera los formularios a partir del esquema oficial: si el SRI cambia `at.xsd`,
  basta con importar el nuevo.
- Las ventanas se adaptan a la pantalla: los formularios pasan de 1 a 4 columnas según
  el ancho, y las ventanas recuerdan su tamaño.
- Valida en tres niveles:
  1. **Formato** de cada campo (longitudes, patrones, fechas, montos).
  2. **Esquema XSD oficial** (lo mismo que verifica el SRI al cargar).
  3. **Reglas de la ficha técnica**: fechas dentro del período, fecha de registro ≥ emisión,
     sustento válido para el tipo de comprobante (tabla 4), forma de pago obligatoria
     sobre USD 500, duplicados, cédulas y RUC, total de ventas calculado como DIMM (desde 2016
     solo suman las ventas con emisión física F; las notas de crédito restan), ventas por
     establecimiento iguales al total, coherencia del IVA, etc.
- **Importa comprobantes electrónicos**: arrastre a la ventana los XML descargados del SRI
  (comprobantes recibidos), los PDF (RIDE) de sus propias facturas, un ZIP o una carpeta,
  o use *Anexo → Importar comprobantes electrónicos*. Los comprobantes emitidos a su RUC
  van a Compras; los emitidos por su RUC van a Ventas, agrupados por cliente y tipo de
  comprobante, con tipo de emisión F (así DIMM los suma al total de ventas), y se actualizan las ventas por establecimiento y el total
  de ventas. Como el portal no entrega el XML de las ventas, se lee el PDF: la clave de
  acceso (con dígito verificador) da tipo, fecha, serie y secuencial, y del texto se toman
  cliente, subtotales, IVA y forma de cobro; si la suma no cuadra con el total, se avisa.
  La aplicación recuerda qué ventas ya importó en cada anexo para no sumarlas dos veces.
- **Importa comprobantes de retención** (XML versiones 1.0.0 y 2.0.0, o PDF):
  - las que le hicieron sus clientes se suman en *Ret. IVA* y *Ret. renta* de la venta de
    ese cliente (deben ser del mismo período del anexo);
  - las que usted emitió a sus proveedores se registran en la compra que sustentan: el IVA
    retenido en el casillero de su porcentaje (10, 20, 30, 50, 70 o 100 %), la renta en el
    detalle AIR (código, base, porcentaje y valor) y la serie, secuencial, autorización y
    fecha del comprobante de retención. Si la factura se importa en el mismo lote, la
    retención se aplica después de crearla. Se admiten facturas, notas de crédito, notas de débito y liquidaciones de
  compra. Antes de agregarlos se muestra una vista previa que descarta los comprobantes de
  otro comprador, de otro período, de pruebas, no autorizados o ya registrados. El sustento
  tributario se toma de compras anteriores del mismo proveedor (o el que usted elija) y las
  retenciones quedan en cero para completarlas a mano.
- Exporta `ATmmaaaa.zip` (con `AT-mmaaaa.xml` adentro), que es el formato que pide la
  ficha técnica para subir al portal del SRI.

## Instalación

Requiere Python 3.10 o superior.

**Linux / macOS**

```bash
cd ats-app
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/atsapp
```

**Windows** (PowerShell o CMD)

```bat
cd ats-app
py -m venv .venv
.venv\Scripts\pip install .
.venv\Scripts\atsapp
```

### Esquema del ATS

El programa trae el esquema oficial `at.xsd`. Si el SRI publica uno nuevo, se puede
actualizar sin reinstalar desde *Herramientas → Importar esquema del SRI* (eligiendo el
plugin del ATS `ats.plugin.X.zip`, una carpeta de DIMM o el `at.xsd`), o desde la consola:

```bash
atsapp-cli importar ats.plugin.1.20.0.zip
```

El esquema importado se guarda en la carpeta de datos del usuario y tiene prioridad sobre el
incluido: Linux `~/.local/share/atsapp/`, Windows `%APPDATA%\atsapp\`, macOS
`~/Library/Application Support/atsapp/`.

## Guardar

- **Guardar** (Ctrl+S): guarda el anexo en el archivo con el que se está trabajando.
- **Guardar en…** (Ctrl+Shift+G): guarda una copia en otra carpeta (XML o ZIP) y se sigue
  trabajando con el archivo actual.
- **Exportar para el SRI** (Ctrl+E): valida y genera `ATmmaaaa.zip`.

## Uso desde la consola

```bash
atsapp-cli validar AT-012026.xml      # muestra errores y advertencias
atsapp-cli exportar AT-012026.xml     # genera AT012026.zip si no hay errores
```

## Catálogos

Los códigos (tipos de comprobante, sustentos, formas de pago, países, etc.) se
transcribieron de la ficha técnica pública del ATS en `atsapp/datos/catalogos.yaml`.
Para agregar o corregir valores sin tocar el programa, cree un `catalogos.yaml` en la
carpeta de datos del usuario con las tablas a reemplazar (mismo formato).

La ficha de febrero de 2025 no incluye la tarifa de IVA del 15 % (vigente desde abril de
2024); se agregó en `tarifas_iva`. La comprobación del IVA solo genera advertencias.

## Ejecutables para Windows, macOS y Linux

Para usar el programa sin instalar Python se construye un ejecutable. Cada sistema genera
el suyo (PyInstaller no crea ejecutables para otros sistemas):

| Sistema | Cómo construir | Resultado en `dist/` |
|---|---|---|
| Windows | doble clic en `empaquetar\construir-windows.bat` | `EditorATS.exe` |
| macOS | doble clic en `empaquetar/construir-mac.command` | `EditorATS.app` |
| Linux | `./empaquetar/construir-linux.sh` | `EditorATS` |

Se necesita Python 3.10 o superior en la máquina donde se construye (no en la que lo usa).
Además se genera `dist/EditorATS-<versión>-<sistema>.zip`, listo para compartir.

**Con GitHub**, sin tener Windows ni Mac: suba el proyecto a un repositorio y en la pestaña
*Actions* ejecute «Construir ejecutables». GitHub construye los de Windows, Mac (Apple e
Intel) y Linux y los deja para descargar como *Artifacts*.

Al abrirlos por primera vez:
- **Windows** puede mostrar «Windows protegió su PC»: *Más información → Ejecutar de todas formas*.
- **macOS** puede decir que no puede verificar al desarrollador: clic derecho sobre la
  aplicación → *Abrir* → *Abrir*.
- **Linux**: si no abre con doble clic, dar permiso de ejecución (`chmod +x EditorATS`).

Estos avisos aparecen porque el ejecutable no está firmado digitalmente (la firma requiere
certificados de pago de Microsoft y Apple).

## Desarrollo

```bash
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

Las pruebas importan `at.xsd` desde `../ats.plugin.*.zip` (o `ATSAPP_PLUGIN_ATS`) y
usan un anexo real solo si se indica en `ATSAPP_ANEXO_REAL` (y PDF de ventas en `ATSAPP_PDF_VENTAS`).

### Estructura

```
atsapp/
  esquema.py        lee at.xsd: estructura, orden y restricciones de cada campo
  documento.py      modelo del anexo, lectura y escritura XML/ZIP
  validacion.py     validación de formato y XSD
  reglas.py         reglas de negocio de la ficha técnica
  catalogos.py      tablas de códigos con vigencias
  identificacion.py cédula y RUC
  comprobantes.py   lectura de facturas electrónicas (XML y PDF) y conversión a compras/ventas
  retenciones.py    comprobantes de retención y su registro en compras o ventas
  importador.py     obtiene at.xsd desde DIMM o el plugin del SRI
  ui/               interfaz Qt (ventana, tablas, formularios adaptables)
  datos/            catálogos y textos de la interfaz (YAML)
```
