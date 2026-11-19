#!/usr/bin/env python3
"""Prueba el parseo de la respuesta del predictor con un payload sintético.

No toca la red: verifica que la forma del JSON de red.cl se traduce bien a la
estructura que consumen los sensores.

    python3 scripts/test_parseo.py
"""

import sys

from probar_api import _cargar

PAYLOAD = {
    "paradero": "PA433",
    "nomett": "Parada 5 / Metro Los Heroes",
    "horaprediccion": "19/11/2026 10:15:02",
    "x": "-70.6693",
    "y": "-33.4443",
    "servicios": {
        "item": [
            {
                "servicio": "506",
                "destino": "Peñalolén",
                "codigorespuesta": "00",
                "respuestaServicio": "Informacion de tiempos de los proximos 2 buses",
                "horaprediccionbus1": "Entre 06 Y 08 min. ",
                "distanciabus1": "2633",
                "ppubus1": "BJFV-75",
                "horaprediccionbus2": "Llegando.",
                "distanciabus2": "479",
                "ppubus2": "CJRY-88",
                "itinerario": True,
            },
            {
                "servicio": "210",
                "destino": "Maipú",
                "codigorespuesta": "00",
                "respuestaServicio": "Informacion de tiempos de los proximos 2 buses",
                "horaprediccionbus1": "Menos de 5 min.",
                "distanciabus1": "801",
                "ppubus1": "PFXC-51",
            },
            {
                "servicio": "J10",
                "destino": None,
                "codigorespuesta": "11",
                "respuestaServicio": "Servicio fuera de horario de operacion",
            },
            # Código "01": un solo bus, con los campos del segundo vacíos.
            # Caso real visto en PI369; antes se descartaba por completo.
            {
                "servicio": "401",
                "destino": "Las Condes",
                "codigorespuesta": "01",
                "respuestaServicio": "Información de tiempo de un bus",
                "horaprediccionbus1": "Llegando",
                "distanciabus1": "18",
                "ppubus1": "TBFP-63",
                "horaprediccionbus2": "",
                "distanciabus2": "",
                "ppubus2": "",
            },
        ]
    },
}

FALLOS = []


def check(nombre, obtenido, esperado):
    if obtenido == esperado:
        print(f"  ok   {nombre}")
    else:
        print(f"  FALLO {nombre}: esperado {esperado!r}, obtenido {obtenido!r}")
        FALLOS.append(nombre)


def main():
    api, _ = _cargar()
    datos = api._normalizar_paradero(PAYLOAD)

    print("Paradero:")
    check("codigo", datos["codigo"], "PA433")
    check("nombre", datos["nombre"], "Parada 5 / Metro Los Heroes")
    check("nº servicios", len(datos["servicios"]), 4)

    s506, s210, j10, s401 = datos["servicios"]

    print("Línea 506 (dos buses):")
    check("linea", s506["linea"], "506")
    check("destino", s506["destino"], "Peñalolén")
    check("nº llegadas", len(s506["llegadas"]), 2)
    check("bus1 min", s506["llegadas"][0]["minutos_min"], 6)
    check("bus1 max", s506["llegadas"][0]["minutos_max"], 8)
    check("bus1 distancia", s506["llegadas"][0]["distancia_m"], 2633)
    check("bus1 patente", s506["llegadas"][0]["patente"], "BJFV-75")
    check("bus2 'Llegando' -> 0", s506["llegadas"][1]["minutos_min"], 0)

    print("Línea 210 (un solo bus):")
    check("nº llegadas", len(s210["llegadas"]), 1)
    check("'Menos de 5' -> min 0", s210["llegadas"][0]["minutos_min"], 0)
    check("'Menos de 5' -> max 5", s210["llegadas"][0]["minutos_max"], 5)

    print("Línea J10 (fuera de horario):")
    check("sin llegadas", j10["llegadas"], [])
    check("mensaje", j10["mensaje"], "Servicio fuera de horario de operacion")

    print("Línea 401 (código 01, un solo bus):")
    check("nº llegadas", len(s401["llegadas"]), 1)
    check("'Llegando' sin punto -> 0", s401["llegadas"][0]["minutos_min"], 0)
    check("distancia", s401["llegadas"][0]["distancia_m"], 18)
    check("patente", s401["llegadas"][0]["patente"], "TBFP-63")

    print("Orden combinado (todas las líneas, por minutos):")
    candidatas = sorted(
        (ll["minutos_min"], s["linea"])
        for s in datos["servicios"]
        for ll in s["llegadas"]
        if ll["minutos_min"] is not None
    )
    check("próximo", candidatas[0][1], "210")  # empata a 0 con 506, gana por orden
    check("nº candidatas", len(candidatas), 4)

    print()
    if FALLOS:
        print(f"{len(FALLOS)} fallo(s): {', '.join(FALLOS)}")
        return 1
    print("Todo correcto.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
