"""Cliente del servidor de Red Regional (DTPR), para ciudades fuera de Santiago.

Sigue el mismo esquema que el cliente de red.cl (api_utils.py): síncrono,
ejecutado por Home Assistant en un executor, con caché y reintentos. Y
devuelve los datos con la MISMA forma, para que los sensores no tengan que
saber de qué sistema vienen.

Diferencias con red.cl que condicionan el diseño:

- No hay token: el servidor responde a peticiones normales.
- La respuesta de un paradero no trae ni su nombre ni el destino de cada
  línea. Ambos salen del GTFS de la ciudad, que se descarga aparte.
- Cada ciudad usa su propio formato de código de paradero (P44723, PF-175,
  MERVAL-01, 75...), y un código inexistente no da error: devuelve listas
  vacías. Por eso los paraderos se validan contra el GTFS, no con un patrón.
- Cada llegada trae una hora exacta además del rango de texto, así que los
  minutos se calculan a partir de esa hora.
"""

import csv
import io
import logging
import threading
import time
import unicodedata
import zipfile
from datetime import datetime, timezone
from urllib.parse import quote

from .api_utils import _a_entero, _get, _get_json, clave_linea, parse_tiempo
from .const import (
    GTFS_MAX_BYTES,
    GTFS_REVISION_TTL,
    PREDICCION_CACHE_TTL,
    REGIONAL_URL,
    ZONAS_TTL,
)

_LOGGER = logging.getLogger(__name__)

_lock = threading.Lock()
_zonas = {"datos": None, "ts": 0.0}
_indices = {}  # zona_uuid -> {"version", "indice", "revisado"}
_cache_prediccion = {}  # (zona_uuid, codigo) -> (timestamp, datos)

# Paradas que el GTFS marca como ficticias (puntos de control, no paraderos).
MARCA_FICTICIA = "parada ficticia"


def normalizar_texto(texto):
    """Minúsculas y sin tildes, para buscar 'Concepcion' o 'concepción'."""
    sin_tildes = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sin_tildes if not unicodedata.combining(c)).lower().strip()


def normalizar_codigo(texto):
    """Los códigos se comparan en mayúsculas y sin espacios alrededor."""
    return (texto or "").strip().upper()


# ---------------------------------------------------------------------------
# Ciudades
# ---------------------------------------------------------------------------

def listar_zonas():
    """Ciudades de Red Regional: [{'uuid', 'nombre'}], ordenadas por nombre."""
    with _lock:
        if _zonas["datos"] and time.time() - _zonas["ts"] < ZONAS_TTL:
            return _zonas["datos"]

    datos = _get_json(f"{REGIONAL_URL}/zones")
    if not isinstance(datos, list):
        with _lock:
            return _zonas["datos"] or []

    zonas = []
    for item in datos:
        if not isinstance(item, dict):
            continue
        uuid = item.get("public_id")
        nombre = item.get("public_name") or item.get("name")
        if uuid and nombre:
            zonas.append({"uuid": uuid, "nombre": nombre.strip()})
    zonas.sort(key=lambda z: normalizar_texto(z["nombre"]))

    with _lock:
        _zonas["datos"] = zonas
        _zonas["ts"] = time.time()
    return zonas


# ---------------------------------------------------------------------------
# GTFS: paraderos, líneas y destinos de una ciudad
# ---------------------------------------------------------------------------

def _leer_tabla(archivo_zip, nombres):
    """Primera tabla que exista de `nombres`, como lista de dicts.

    El GTFS de Red Regional separa con ';' en vez de ','. Detectamos el
    separador por la cabecera, por si alguna ciudad usa el estándar.
    """
    disponibles = set(archivo_zip.namelist())
    for nombre in nombres:
        if nombre not in disponibles:
            continue
        if archivo_zip.getinfo(nombre).file_size > GTFS_MAX_BYTES:
            _LOGGER.warning("La tabla %s del GTFS es demasiado grande; se ignora", nombre)
            return []
        texto = archivo_zip.read(nombre).decode("utf-8-sig", errors="replace")
        cabecera = texto.split("\n", 1)[0]
        separador = ";" if cabecera.count(";") > cabecera.count(",") else ","
        return list(csv.DictReader(io.StringIO(texto), delimiter=separador))
    return []


def parse_gtfs(contenido):
    """Índice de paraderos y destinos a partir del ZIP de un GTFS.

    Devuelve {'paraderos': {CODIGO: {...}}, 'destinos': {(linea, sentido): texto}}.
    Un ZIP dañado da un índice vacío en vez de una excepción.
    """
    indice = {"paraderos": {}, "destinos": {}}
    try:
        archivo_zip = zipfile.ZipFile(io.BytesIO(contenido))
    except zipfile.BadZipFile:
        _LOGGER.warning("El GTFS descargado no es un ZIP válido")
        return indice

    for fila in _leer_tabla(archivo_zip, ("stop.csv", "stops.txt")):
        codigo = normalizar_codigo(fila.get("stop_code") or fila.get("stop_id"))
        if not codigo or codigo in indice["paraderos"]:
            continue
        lineas = [r.strip() for r in (fila.get("routes") or "").split("|") if r.strip()]
        indice["paraderos"][codigo] = {
            "codigo": codigo,
            "nombre": (fila.get("name") or fila.get("stop_name") or "").strip(),
            "lineas": lineas,
        }

    for fila in _leer_tabla(archivo_zip, ("route.csv",)):
        linea = (fila.get("route_name") or "").strip()
        sentido = (fila.get("direction") or "").strip()
        destino = (fila.get("headsign") or "").strip()
        if linea and destino:
            # Hay una fila por variante y tipo de día; el destino se repite.
            indice["destinos"].setdefault((linea, sentido), destino)

    return indice


def obtener_indice(zona_uuid):
    """Índice GTFS de la ciudad, descargándolo solo si cambió de versión.

    Si no se puede consultar, devuelve el último índice conocido (o None).
    """
    with _lock:
        cacheado = _indices.get(zona_uuid)
    if cacheado and time.time() - cacheado["revisado"] < GTFS_REVISION_TTL:
        return cacheado["indice"]

    base = f"{REGIONAL_URL}/{quote(zona_uuid, safe='')}/gtfs"
    info = _get_json(f"{base}/version/3")
    version = info.get("version") if isinstance(info, dict) else None

    if cacheado and version and version == cacheado["version"]:
        with _lock:
            cacheado["revisado"] = time.time()
        return cacheado["indice"]

    respuesta = _get(f"{base}/download/3", timeout=60)
    if respuesta is None:
        return cacheado["indice"] if cacheado else None

    indice = parse_gtfs(respuesta.content)
    if not indice["paraderos"]:
        return cacheado["indice"] if cacheado else None

    with _lock:
        _indices[zona_uuid] = {"version": version, "indice": indice, "revisado": time.time()}
    _LOGGER.debug(
        "GTFS de %s cargado: %s paraderos", zona_uuid, len(indice["paraderos"])
    )
    return indice


def buscar_paradero(zona_uuid, codigo):
    """El paradero con ese código en esa ciudad, o None si no existe."""
    indice = obtener_indice(zona_uuid)
    if indice is None:
        return None
    return indice["paraderos"].get(normalizar_codigo(codigo))


def buscar_paraderos_por_nombre(zona_uuid, texto):
    """Paraderos cuyo nombre contiene todas las palabras de `texto`.

    Se excluyen las paradas ficticias (puntos de control del GTFS).

    Devuelve None si no se pudo cargar el GTFS de la ciudad.
    """
    indice = obtener_indice(zona_uuid)
    if indice is None:
        return None

    # Basta con que aparezcan todas las palabras, en cualquier orden: los
    # paraderos se llaman por cruces ("Av. Argentina esq. Victoria"), así que
    # "argentina victoria" o "victoria argentina" deben encontrarlo.
    palabras = normalizar_texto(texto).split()
    if not palabras:
        return []
    encontrados = []
    for paradero in indice["paraderos"].values():
        nombre = normalizar_texto(paradero["nombre"])
        if MARCA_FICTICIA in nombre:
            continue
        if all(palabra in nombre for palabra in palabras):
            encontrados.append(paradero)
    encontrados.sort(key=lambda p: (normalizar_texto(p["nombre"]), p["codigo"]))
    return encontrados


# ---------------------------------------------------------------------------
# Predicciones
# ---------------------------------------------------------------------------

def _llegada(prediccion, ahora):
    texto = (prediccion.get("timeLabel") or "").strip()
    minimo, maximo = parse_tiempo(texto)

    epoch = prediccion.get("epochTime")
    if isinstance(epoch, (int, float)):
        minutos = max(0, int((epoch - ahora) // 60))
        hora_llegada = datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
    else:
        minutos = minimo
        hora_llegada = None

    return {
        "minutos": minutos,
        "minutos_min": minimo,
        "minutos_max": maximo,
        "texto": texto,
        "distancia_m": _a_entero(prediccion.get("distance")),
        "patente": (prediccion.get("licensePlate") or "").strip() or None,
        "hora_llegada": hora_llegada,
        "tiempo_real": bool(prediccion.get("realtime")),
    }


def normalizar_respuesta(codigo, datos, indice, ahora):
    """Respuesta de stopInfo con la misma forma que la de red.cl.

    El servidor manda TODAS las micros que vienen (más de cien en un paradero
    céntrico): las agrupamos por línea y nos quedamos con las dos primeras.
    Las líneas sin buses en camino aparecen en `routeInfo` con un mensaje de
    frecuencia, igual que los servicios sin predicción de red.cl.

    Ignoramos a propósito `events`: son reportes de usuarios sobre el
    paradero (por ejemplo, "Paradero en buen estado"), no avisos del servicio.
    """
    paraderos = indice["paraderos"] if indice else {}
    destinos = indice["destinos"] if indice else {}

    por_linea = {}
    for prediccion in datos.get("predictions") or []:
        if not isinstance(prediccion, dict):
            continue
        linea = (prediccion.get("route") or "").strip()
        if linea:
            por_linea.setdefault(linea, []).append(prediccion)

    servicios = []
    for linea, predicciones in por_linea.items():
        predicciones.sort(key=lambda p: p.get("epochTime") or float("inf"))
        llegadas = [_llegada(p, ahora) for p in predicciones[:2]]
        sentido = (predicciones[0].get("direction") or "").strip()
        en_tiempo_real = any(ll["tiempo_real"] for ll in llegadas)
        servicios.append({
            "linea": linea,
            "destino": destinos.get((linea, sentido)),
            "codigo_respuesta": "",
            "mensaje": "Tiempo real" if en_tiempo_real else "Horario programado",
            "llegadas": llegadas,
        })

    for info in datos.get("routeInfo") or []:
        if not isinstance(info, dict):
            continue
        linea = (info.get("servicio") or "").strip()
        if not linea or linea in por_linea:
            continue
        servicios.append({
            "linea": linea,
            "destino": None,
            "codigo_respuesta": "",
            "mensaje": (info.get("msg") or "").strip(),
            "llegadas": [],
        })

    servicios.sort(key=lambda s: clave_linea(s["linea"]))
    paradero = paraderos.get(codigo) or {}

    return {
        "codigo": codigo,
        "nombre": paradero.get("nombre") or codigo,
        "hora_prediccion": time.strftime("%H:%M", time.localtime(ahora)),
        "servicios": servicios,
    }


def consultar_paradero(zona_uuid, codigo, intentos=3, espera=1, cache_ttl=PREDICCION_CACHE_TTL):
    """Llegadas a un paradero de Red Regional, o None si no se pudo consultar."""
    codigo = normalizar_codigo(codigo)
    clave = (zona_uuid, codigo)

    if cache_ttl:
        with _lock:
            cacheado = _cache_prediccion.get(clave)
        if cacheado and time.time() - cacheado[0] < cache_ttl:
            return cacheado[1]

    url = (
        f"{REGIONAL_URL}/{quote(zona_uuid, safe='')}/stopInfo"
        f"?stopCode={quote(codigo, safe='')}"
    )

    for intento in range(intentos):
        datos = _get_json(url)
        if isinstance(datos, dict) and "predictions" in datos:
            # El GTFS solo aporta nombres y destinos: si falla, las
            # llegadas siguen sirviendo.
            indice = obtener_indice(zona_uuid)
            normalizado = normalizar_respuesta(codigo, datos, indice, time.time())
            if cache_ttl:
                with _lock:
                    _cache_prediccion[clave] = (time.time(), normalizado)
            return normalizado

        if intento < intentos - 1:
            time.sleep(espera)

    _LOGGER.debug("No se pudo consultar el paradero %s de %s", codigo, zona_uuid)
    return None


def lineas_del_paradero(zona_uuid, codigo):
    """Líneas de un paradero para el modo "una entidad por línea".

    Usa las que el servidor informa ahora (con buses o con frecuencia), igual
    que en Santiago. Si a esa hora no informa ninguna (de noche, por ejemplo),
    recurre a las que el GTFS asigna al paradero.
    """
    datos = consultar_paradero(zona_uuid, codigo, intentos=2, cache_ttl=0)
    lineas = {s["linea"] for s in (datos or {}).get("servicios", []) if s.get("linea")}
    if not lineas:
        paradero = buscar_paradero(zona_uuid, codigo) or {}
        lineas = set(paradero.get("lineas", []))
    return sorted(lineas, key=clave_linea)
