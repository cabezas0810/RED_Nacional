#!/usr/bin/env python3
"""Comprueba contra red.cl, sin Home Assistant, que la integración funciona.

Uso:
    python3 scripts/probar_api.py PA433
    python3 scripts/probar_api.py PA433 506     # filtrando por línea

Sirve para verificar que el predictor de red.cl sigue respondiendo y que el
token se obtiene bien, antes de culpar a Home Assistant.
"""

import importlib.util
import pathlib
import sys
import types

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PAQUETE = RAIZ / "custom_components" / "red_movilidad"


def _cargar():
    """Carga const.py y api_utils.py sin necesitar Home Assistant instalado."""
    paquete = types.ModuleType("red_movilidad")
    paquete.__path__ = [str(PAQUETE)]
    sys.modules["red_movilidad"] = paquete

    for nombre in ("const", "api_utils"):
        spec = importlib.util.spec_from_file_location(
            f"red_movilidad.{nombre}", PAQUETE / f"{nombre}.py"
        )
        modulo = importlib.util.module_from_spec(spec)
        sys.modules[f"red_movilidad.{nombre}"] = modulo
        spec.loader.exec_module(modulo)

    return sys.modules["red_movilidad.api_utils"]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    codigo = sys.argv[1].upper()
    linea = sys.argv[2] if len(sys.argv) > 2 else None

    api = _cargar()

    token = api.obtener_token(codigo)
    print(f"Token: {'obtenido' if token else 'NO se pudo obtener'}")
    if not token:
        print("Sin token no hay predicción. ¿Responde https://www.red.cl ?")
        return 2

    datos = api.consultar_paradero(codigo, cache_ttl=0)
    if datos is None:
        print(f"No se pudo consultar el paradero {codigo}.")
        print("El predictor de red.cl falla a menudo: reintenta en unos segundos.")
        return 3

    print(f"\nParadero {datos['codigo']} - {datos['nombre']}")
    print(f"Hora de predicción: {datos['hora_prediccion']}\n")

    for servicio in datos["servicios"]:
        if linea and servicio["linea"].lower() != linea.lower():
            continue

        cabecera = f"  Línea {servicio['linea']}"
        if servicio.get("destino"):
            cabecera += f" -> {servicio['destino']}"
        print(cabecera)

        if not servicio["llegadas"]:
            print(f"      (sin buses: {servicio['mensaje'] or servicio['codigo_respuesta']})")
            continue

        for i, llegada in enumerate(servicio["llegadas"], start=1):
            distancia = llegada["distancia_m"]
            km = f"{distancia / 1000:.1f} km" if distancia is not None else "distancia n/d"
            patente = llegada["patente"] or "s/patente"
            print(f"      Bus {i}: {llegada['texto']:<24} {km:>10}  {patente}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
