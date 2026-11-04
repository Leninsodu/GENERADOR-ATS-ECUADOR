"""Construye el ejecutable del Editor ATS para el sistema operativo donde se ejecuta.

Uso (desde la carpeta del proyecto, con el entorno virtual creado):

    Linux / macOS:  .venv/bin/python empaquetar/construir.py
    Windows:        .venv\\Scripts\\python empaquetar\\construir.py

Resultado en la carpeta dist/:
    Windows  EditorATS.exe           (un solo archivo)
    Linux    EditorATS               (un solo archivo)
    macOS    EditorATS.app           (aplicación)
y un ZIP listo para compartir: dist/EditorATS-<versión>-<sistema>.zip

PyInstaller no genera ejecutables para otros sistemas: el de Windows se construye en
Windows y el de macOS en una Mac (o con GitHub Actions, ver .github/workflows).
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
NOMBRE = "EditorATS"


def main() -> int:
    sistema = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(platform.system())
    if sistema is None:
        print(f"Sistema no soportado: {platform.system()}", file=sys.stderr)
        return 1
    sys.path.insert(0, str(RAIZ))
    from atsapp import __version__

    dist, build = RAIZ / "dist", RAIZ / "build"
    shutil.rmtree(build, ignore_errors=True)
    args = [sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--name", NOMBRE,
            "--windowed", "--collect-data", "atsapp", "--paths", str(RAIZ),
            "--distpath", str(dist), "--workpath", str(build), "--specpath", str(build),
            "--exclude-module", "tkinter", "--exclude-module", "pytest"]
    if sistema != "macos":
        args.append("--onefile")  # en macOS se genera la aplicación .app
    else:
        args += ["--osx-bundle-identifier", "ec.atsapp.editor"]
    args.append(str(RAIZ / "empaquetar" / "lanzador.py"))
    print(" ".join(args))
    subprocess.run(args, check=True)

    destino = dist / f"{NOMBRE}-{__version__}-{sistema}.zip"
    destino.unlink(missing_ok=True)
    if sistema == "macos":
        # ditto conserva los enlaces simbólicos y permisos que necesita la .app
        subprocess.run(["ditto", "-c", "-k", "--keepParent", str(dist / f"{NOMBRE}.app"), str(destino)], check=True)
    else:
        ejecutable = dist / (f"{NOMBRE}.exe" if sistema == "windows" else NOMBRE)
        with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
            import time

            info = zipfile.ZipInfo(ejecutable.name, date_time=time.localtime()[:6])
            info.external_attr = 0o755 << 16  # que siga siendo ejecutable al descomprimir en Linux
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, ejecutable.read_bytes())
    print(f"\nListo: {destino}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
