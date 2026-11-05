"""Verificación de cédulas y RUC ecuatorianos (algoritmos públicos de dígito verificador)."""

from __future__ import annotations


def _provincia_valida(numero: str) -> bool:
    p = int(numero[:2])
    return 1 <= p <= 24 or p == 30


def cedula_valida(cedula: str) -> bool:
    """Cédula de 10 dígitos: código de provincia y dígito verificador (módulo 10).

    No se exige que el tercer dígito sea menor a 6: el Registro Civil ya emite
    cédulas con tercer dígito 6 (el SRI las acepta).
    """
    if len(cedula) != 10 or not cedula.isdigit() or not _provincia_valida(cedula):
        return False
    suma = 0
    for i, c in enumerate(cedula[:9]):
        n = int(c) * (2 if i % 2 == 0 else 1)
        suma += n - 9 if n > 9 else n
    verificador = (10 - suma % 10) % 10
    return verificador == int(cedula[9])


def _modulo11(digitos: str, coeficientes: list[int], verificador: int) -> bool:
    suma = sum(int(d) * c for d, c in zip(digitos, coeficientes))
    resto = suma % 11
    esperado = 0 if resto == 0 else 11 - resto
    return esperado == verificador


def ruc_valido(ruc: str) -> bool:
    """RUC de 13 dígitos de persona natural, sociedad privada o entidad pública.

    Nota: el SRI ha emitido algunos RUC de sociedades que no cumplen el módulo 11
    clásico, por eso las reglas usan esta verificación solo como advertencia.
    """
    if len(ruc) != 13 or not ruc.isdigit() or not _provincia_valida(ruc):
        return False
    tercero = int(ruc[2])
    if tercero < 6:
        return cedula_valida(ruc[:10]) and ruc[10:] != "000"
    if tercero == 6:
        publico = ruc[9:] != "0000" and _modulo11(ruc[:8], [3, 2, 7, 6, 5, 4, 3, 2], int(ruc[8]))
        natural = cedula_valida(ruc[:10]) and ruc[10:] != "000"
        return publico or natural
    if tercero == 9:
        return ruc[10:] != "000" and _modulo11(ruc[:9], [4, 3, 2, 7, 6, 5, 4, 3, 2], int(ruc[9]))
    return False


def ruc_aceptado(ruc: str) -> bool:
    """Valida el RUC igual que DIMM.

    Exige 13 dígitos terminados en 001. Para personas naturales (tercer dígito 0 a 5) la
    cédula debe cumplir el módulo 10. Para entidades públicas (6) y sociedades (9) DIMM
    calcula el dígito verificador pero no lo exige, porque el SRI emite RUC nuevos que no
    cumplen la fórmula clásica.
    """
    if len(ruc) != 13 or not ruc.isdigit() or ruc[10:] != "001":
        return False
    tercero = int(ruc[2])
    if tercero <= 5:
        return cedula_valida(ruc[:10])
    return tercero in (6, 9)


CONSUMIDOR_FINAL = "9999999999999"


def clave_acceso_valida(clave: str) -> bool:
    """Clave de acceso de comprobante electrónico: 49 dígitos con dígito verificador módulo 11.

    Estructura: fecha (8) + tipo (2) + RUC emisor (13) + ambiente (1) + serie (6) +
    secuencial (9) + código numérico (8) + tipo de emisión (1) + verificador (1).
    """
    if len(clave) != 49 or not clave.isdigit():
        return False
    suma, peso = 0, 2
    for d in reversed(clave[:48]):
        suma += int(d) * peso
        peso = 2 if peso == 7 else peso + 1
    v = 11 - suma % 11
    v = 0 if v == 11 else 1 if v == 10 else v
    return v == int(clave[48])


def ruc_en_clave_acceso(clave: str) -> str:
    return clave[10:23] if clave_acceso_valida(clave) else ""
