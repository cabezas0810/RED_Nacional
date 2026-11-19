#!/usr/bin/env python3
"""Prueba la parte de Red Regional sin tocar la red.

Usa datos sintéticos con la forma que devuelve el servidor real: un GTFS con
';' como separador y una respuesta de paradero con horas exactas.

    python3 scripts/test_regional.py
"""

import io
import sys
import time
import zipfile

from probar_api import _cargar

FALLOS = []


def check(nombre, obtenido, esperado):
    if obtenido == esperado:
        print(f"  ok   {nombre}")
    else:
        print(f"  FALLO {nombre}: esperado {esperado!r}, obtenido {obtenido!r}")
        FALLOS.append(nombre)


def gtfs_sintetico():
    """ZIP con las dos tablas que usamos, separadas por ';' como las reales."""
    paraderos = (
        "mode;stop_id;name;stop_lat;stop_lon;routes;resource_id;stop_code\n"
        "3;1039;Diego Portales esq. Arturo Prat;-38.7;-72.6;1A|10B|2B;0;1039\n"
        "3;1040;Diego Portales esq. Arturo Prat;-38.7;-72.6;1A|1B;0;1040\n"
        "3;PF-175;Av. Tucapel esq. Bilbao;-18.4;-70.3;3;0;PF-175\n"
        "3;PF-999;(Parada Ficticia) Av. Tucapel esq. Bilbao;-18.4;-70.3;3;0;PF-999\n"
        "3;77;Caupolicán esq. Lynch;-38.7;-72.6;2B;0;77\n"
    )
    recorridos = (
        "mode;route_name;direction;variant;day_type;shape_id;schedule;color;headsign\n"
        "3;1A;I;-;L;1A_I;06:00-22:00;#FF0000;Cajón\n"
        "3;1A;I;-;S;1A_I;06:00-22:00;#FF0000;Cajón\n"
        "3;1A;R;-;L;1A_R;06:00-22:00;#FF0000;Labranza\n"
        "3;10B;R;-;L;10B_R;06:00-22:00;#00FF00;Padre Las Casas\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archivo:
        archivo.writestr("stop.csv", "﻿" + paraderos)  # con BOM, por si acaso
        archivo.writestr("route.csv", recorridos)
    return buffer.getvalue()


AHORA = 1_800_000_000.0

RESPUESTA = {
    "alerts": [],
    # Reporte de usuarios POSITIVO: no debe convertirse en aviso de servicio.
    "events": [{"eventcode": "evn0201", "name": "Paradero en buen estado"}],
    "predictions": [
        # Tres buses de la 1A, desordenados: hay que quedarse con los 2 primeros.
        {"route": "1A", "direction": "I", "epochTime": AHORA + 9 * 60 + 20,
         "timeLabel": "8 a 10 min", "realtime": True, "distance": 1605.4,
         "licensePlate": "LLJT50"},
        {"route": "1A", "direction": "I", "epochTime": AHORA + 30 * 60,
         "timeLabel": "+ de 25 min", "realtime": True, "distance": 9000,
         "licensePlate": "AAAA11"},
        {"route": "1A", "direction": "I", "epochTime": AHORA + 5 * 60 + 40,
         "timeLabel": "4 a 6 min", "realtime": True, "distance": 812.0,
         "licensePlate": "JVXY26"},
        {"route": "10B", "direction": "R", "epochTime": AHORA + 6,
         "timeLabel": "Llegando", "realtime": True, "distance": 120,
         "licensePlate": " DBRD55 "},
        {"route": "2B", "direction": "I", "epochTime": AHORA + 12 * 60,
         "timeLabel": "11 a 15 min", "realtime": False, "distance": None,
         "licensePlate": ""},
    ],
    "routeInfo": [
        {"servicio": "3D", "msg": "Bus pasa cada 12 minutos aprox."},
        {"servicio": "1A", "msg": "No debe pisar a la 1A con buses en camino"},
    ],
}


def main():
    api_utils, regional = _cargar()

    print("parse_tiempo con los textos de Red Regional:")
    check("'10 a 14 min'", api_utils.parse_tiempo("10 a 14 min"), (10, 14))
    check("'+ de 25 min'", api_utils.parse_tiempo("+ de 25 min"), (25, None))
    check("'Llegando'", api_utils.parse_tiempo("Llegando"), (0, 0))
    check("red.cl sigue igual: 'Entre 06 Y 08 min.'", api_utils.parse_tiempo("Entre 06 Y 08 min."), (6, 8))
    check("red.cl sigue igual: 'Mas de 30 min.'", api_utils.parse_tiempo("Mas de 30 min."), (30, None))

    print("Orden natural de líneas:")
    check("1A, 1B, 2B, 10B, B02", sorted(["10B", "B02", "2B", "1B", "1A"], key=api_utils.clave_linea),
          ["1A", "1B", "2B", "10B", "B02"])

    print("GTFS con ';':")
    indice = regional.parse_gtfs(gtfs_sintetico())
    check("nº paraderos", len(indice["paraderos"]), 5)
    check("nombre con BOM leído bien", indice["paraderos"]["1039"]["nombre"], "Diego Portales esq. Arturo Prat")
    check("líneas del paradero", indice["paraderos"]["1039"]["lineas"], ["1A", "10B", "2B"])
    check("código con guion", indice["paraderos"]["PF-175"]["codigo"], "PF-175")
    check("destino 1A ida", indice["destinos"][("1A", "I")], "Cajón")
    check("destino 1A vuelta", indice["destinos"][("1A", "R")], "Labranza")
    check("ZIP dañado -> índice vacío", regional.parse_gtfs(b"no es un zip")["paraderos"], {})

    print("Búsqueda de paraderos (índice inyectado, sin red):")
    zona = "zona-de-prueba"
    regional._indices[zona] = {"version": "x", "indice": indice, "revisado": time.time()}
    check("código exacto", regional.buscar_paradero(zona, "1039")["nombre"], "Diego Portales esq. Arturo Prat")
    check("código en minúsculas", regional.buscar_paradero(zona, "pf-175")["codigo"], "PF-175")
    check("código inexistente", regional.buscar_paradero(zona, "XYZ"), None)
    check("palabras en otro orden",
          [p["codigo"] for p in regional.buscar_paraderos_por_nombre(zona, "prat portales")], ["1039", "1040"])
    check("sin tildes", [p["codigo"] for p in regional.buscar_paraderos_por_nombre(zona, "caupolican")], ["77"])
    check("excluye paradas ficticias",
          [p["codigo"] for p in regional.buscar_paraderos_por_nombre(zona, "tucapel")], ["PF-175"])
    check("búsqueda vacía", regional.buscar_paraderos_por_nombre(zona, "   "), [])

    print("Respuesta de paradero normalizada:")
    datos = regional.normalizar_respuesta("1039", RESPUESTA, indice, AHORA)
    por_linea = {s["linea"]: s for s in datos["servicios"]}
    check("nombre desde el GTFS", datos["nombre"], "Diego Portales esq. Arturo Prat")
    check("orden natural de servicios", [s["linea"] for s in datos["servicios"]], ["1A", "2B", "3D", "10B"])
    check("1A: solo 2 buses de 3", len(por_linea["1A"]["llegadas"]), 2)
    check("1A: el primero es el más cercano en hora", por_linea["1A"]["llegadas"][0]["patente"], "JVXY26")
    check("1A: minutos desde la hora exacta", por_linea["1A"]["llegadas"][0]["minutos"], 5)
    check("1A: rango desde el texto", (por_linea["1A"]["llegadas"][0]["minutos_min"],
                                       por_linea["1A"]["llegadas"][0]["minutos_max"]), (4, 6))
    check("1A: distancia entera", por_linea["1A"]["llegadas"][0]["distancia_m"], 812)
    check("1A: destino según sentido", por_linea["1A"]["destino"], "Cajón")
    check("1A: routeInfo no la duplica", sum(1 for s in datos["servicios"] if s["linea"] == "1A"), 1)
    check("10B: 'Llegando' a 6 s -> 0 min", por_linea["10B"]["llegadas"][0]["minutos"], 0)
    check("10B: patente sin espacios", por_linea["10B"]["llegadas"][0]["patente"], "DBRD55")
    check("2B: sin tiempo real", por_linea["2B"]["mensaje"], "Horario programado")
    check("2B: patente vacía -> None", por_linea["2B"]["llegadas"][0]["patente"], None)
    check("2B: destino desconocido -> None", por_linea["2B"]["destino"], None)
    check("3D: solo frecuencia", (por_linea["3D"]["llegadas"], por_linea["3D"]["mensaje"]),
          ([], "Bus pasa cada 12 minutos aprox."))
    check("los reportes de usuarios no aparecen", "Paradero en buen estado" in str(datos), False)
    check("hora de llegada en ISO", por_linea["10B"]["llegadas"][0]["hora_llegada"].startswith("2027-01-15T"), True)

    print("Sin GTFS disponible, las llegadas siguen funcionando:")
    sin_indice = regional.normalizar_respuesta("1039", RESPUESTA, None, AHORA)
    check("nombre = código", sin_indice["nombre"], "1039")
    check("llegadas intactas", len(sin_indice["servicios"]), 4)

    print("Paradero sin predicciones (respuesta real de un código inexistente):")
    vacio = regional.normalizar_respuesta("XYZ", {"events": [], "alerts": [], "predictions": []}, indice, AHORA)
    check("sin servicios", vacio["servicios"], [])

    print()
    if FALLOS:
        print(f"{len(FALLOS)} fallo(s): {', '.join(FALLOS)}")
        return 1
    print("Todo correcto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
