#!/usr/bin/env python3
"""Comprueba contra los servidores reales, sin Home Assistant, que la integración funciona.

Santiago (red.cl):
    python3 scripts/probar_api.py PA433
    python3 scripts/probar_api.py PA433 506          # filtrando por línea

Regiones (Red Regional):
    python3 scripts/probar_api.py --ciudad Temuco 1039
    python3 scripts/probar_api.py --ciudad Temuco 1039 1A
    python3 scripts/probar_api.py --ciudad Temuco --buscar "portales"
    python3 scripts/probar_api.py --ciudades          # lista de ciudades

Sirve para saber si el servidor sigue respondiendo antes de culpar a Home
Assistant.
"""

import importlib.util
import pathlib
import sys
import types

RAIZ = pathlib.Path(__file__).resolve().parent.parent
PAQUETE = RAIZ / "custom_components" / "red_movilidad"


def _cargar():
    """Carga los clientes sin necesitar Home Assistant instalado."""
    paquete = types.ModuleType("red_movilidad")
    paquete.__path__ = [str(PAQUETE)]
    sys.modules["red_movilidad"] = paquete

    for nombre in ("const", "api_utils", "api_regional"):
        spec = importlib.util.spec_from_file_location(
            f"red_movilidad.{nombre}", PAQUETE / f"{nombre}.py"
        )
        modulo = importlib.util.module_from_spec(spec)
        sys.modules[f"red_movilidad.{nombre}"] = modulo
        spec.loader.exec_module(modulo)

    return sys.modules["red_movilidad.api_utils"], sys.modules["red_movilidad.api_regional"]


def _imprimir(datos, linea):
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
            texto = llegada["texto"]
            if llegada.get("minutos") is not None:
                texto = f"{llegada['minutos']} min ({texto})"
            print(f"      Bus {i}: {texto:<26} {km:>10}  {patente}")


def _santiago(api, args):
    codigo = args[0].upper()
    linea = args[1] if len(args) > 1 else None

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

    _imprimir(datos, linea)
    return 0


def _buscar_zona(regional, nombre):
    zonas = regional.listar_zonas()
    if not zonas:
        print("No se pudo obtener la lista de ciudades de Red Regional.")
        return None
    consulta = regional.normalizar_texto(nombre)
    for zona in zonas:
        if regional.normalizar_texto(zona["nombre"]) == consulta:
            return zona
    coincidencias = [z for z in zonas if consulta in regional.normalizar_texto(z["nombre"])]
    if len(coincidencias) == 1:
        return coincidencias[0]
    print(f"Ciudad '{nombre}' no encontrada. Disponibles:")
    for zona in zonas:
        print(f"  {zona['nombre']}")
    return None


def _regiones(regional, args):
    if args and args[0] == "--ciudades":
        for zona in regional.listar_zonas():
            print(f"  {zona['nombre']}")
        return 0

    if len(args) < 3:
        print(__doc__)
        return 1

    zona = _buscar_zona(regional, args[1])
    if zona is None:
        return 2

    if args[2] == "--buscar":
        texto = " ".join(args[3:])
        encontrados = regional.buscar_paraderos_por_nombre(zona["uuid"], texto)
        if encontrados is None:
            print("No se pudo descargar la lista de paraderos de la ciudad.")
            return 3
        print(f"{len(encontrados)} paraderos en {zona['nombre']} contienen '{texto}':")
        for p in encontrados[:40]:
            print(f"  {p['codigo']:<12} {p['nombre']}  ({', '.join(p['lineas'][:6])})")
        return 0

    codigo = args[2]
    linea = args[3] if len(args) > 3 else None

    paradero = regional.buscar_paradero(zona["uuid"], codigo)
    if paradero is None:
        print(f"El paradero {codigo} no existe en {zona['nombre']} (o no se pudo leer el GTFS).")
        return 3

    datos = regional.consultar_paradero(zona["uuid"], codigo, cache_ttl=0)
    if datos is None:
        print(f"No se pudo consultar el paradero {codigo} de {zona['nombre']}.")
        return 3

    print(f"Ciudad: {zona['nombre']}")
    _imprimir(datos, linea)
    return 0


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 1

    santiago, regional = _cargar()
    if args[0] in ("--ciudad", "--ciudades"):
        return _regiones(regional, args)
    return _santiago(santiago, args)


if __name__ == "__main__":
    sys.exit(main())
