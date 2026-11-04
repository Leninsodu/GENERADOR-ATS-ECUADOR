"""Punto de entrada.

    atsapp                       abre la interfaz gráfica
    atsapp ARCHIVO.xml           abre la interfaz con un anexo
    atsapp validar ARCHIVO       valida un anexo en la consola
    atsapp importar RUTA         importa el esquema at.xsd desde DIMM o el plugin del ATS
    atsapp exportar ARCHIVO.xml  genera ATmmaaaa.zip junto al archivo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _consola(args: list[str]) -> int:
    from . import importador, rutas
    from .catalogos import Catalogos
    from .documento import Documento
    from .esquema import Esquema
    from .presentacion import describir_ruta
    from .validacion import validar_documento

    p = argparse.ArgumentParser(prog="atsapp")
    sub = p.add_subparsers(dest="orden", required=True)
    v = sub.add_parser("validar", help="valida un anexo XML o ZIP")
    v.add_argument("archivo")
    v.add_argument("--xsd", help="ruta a at.xsd (por defecto, el importado)")
    i = sub.add_parser("importar", help="importa el esquema at.xsd")
    i.add_argument("ruta", help="carpeta de DIMM, plugin del ATS (.zip), JAR o at.xsd")
    e = sub.add_parser("exportar", help="genera el ZIP para el SRI")
    e.add_argument("archivo")
    e.add_argument("--forzar", action="store_true", help="exportar aunque haya errores")
    a = p.parse_args(args)

    if a.orden == "importar":
        enc = importador.importar_esquema(a.ruta)
        print(f"Esquema importado desde {enc.origen}\n -> {rutas.ruta_esquema_usuario()}")
        return 0

    xsd = Path(getattr(a, "xsd", None) or rutas.ruta_esquema())
    if not xsd.is_file():
        print(f"No se encontró el esquema {xsd}", file=sys.stderr)
        return 2
    esquema = Esquema(xsd)
    doc = Documento.desde_archivo(esquema, a.archivo)
    mensajes = validar_documento(doc, Catalogos.cargar())
    errores = [m for m in mensajes if m.es_error]
    for m in mensajes:
        print(f"[{m.severidad.texto}] {describir_ruta(m.ruta)}: {m.texto}")
    print(f"\n{len(errores)} error(es), {len(mensajes) - len(errores)} advertencia(s).")
    if a.orden == "exportar":
        if errores and not a.forzar:
            print("No se exportó porque hay errores (use --forzar).", file=sys.stderr)
            return 1
        destino = Path(a.archivo).with_name(doc.nombre_sugerido(".zip"))
        doc.guardar_zip(destino)
        print(f"Generado: {destino}")
    return 1 if errores else 0


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] in ("validar", "importar", "exportar", "-h", "--help"):
        return _consola(args)
    from .ui.aplicacion import ejecutar

    return ejecutar(args)


if __name__ == "__main__":
    sys.exit(main())
