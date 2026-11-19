"""Cliente de los servicios de red.cl.

Todo el módulo es síncrono: Home Assistant lo ejecuta en un executor, igual
que hace la integración de Zaragoza en la que está basado.

El predictor de red.cl no es una API pública: hay que leer de la web un token
JWT que caduca, así que aquí se gestionan token, caché y reintentos.
"""

import base64
import logging
import re
import threading
import time
from urllib.parse import quote

import requests

from .const import (
    PARADERO_PAGE_URL,
    PREDICCION_CACHE_TTL,
    PREDICCION_URL,
    RECORRIDO_URL,
    SERVICIOS_URL,
    TOKEN_TTL,
    USER_AGENT,
)

_LOGGER = logging.getLogger(__name__)

# La web inyecta el token así:  $jwt = 'ZXlKMGVYQWlPaUpLVjFRaUxDSmhiR2Np...';
RE_JWT = re.compile(r"\$jwt\s*=\s*'([^']+)'")

# Formatos de tiempo que devuelve el predictor.
RE_ENTRE = re.compile(r"entre\s+0*(\d+)\s*y\s*0*(\d+)\s*min", re.IGNORECASE)
# Red Regional usa "10 a 14 min" donde red.cl dice "Entre 10 Y 14 min".
RE_RANGO_A = re.compile(r"0*(\d+)\s+a\s+0*(\d+)\s*min", re.IGNORECASE)
RE_MENOS_DE = re.compile(r"menos\s+de\s+0*(\d+)\s*min", re.IGNORECASE)
# "Mas de 30 min." en red.cl, "+ de 25 min" en Red Regional.
RE_MAS_DE = re.compile(r"(?:m[áa]s|\+)\s*de\s+0*(\d+)\s*min", re.IGNORECASE)
RE_MIN = re.compile(r"0*(\d+)\s*min", re.IGNORECASE)

_lock = threading.Lock()
_token = {"valor": None, "ts": 0.0}
_cache_prediccion = {}  # codigo -> (timestamp, datos)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

def _get(url, timeout=15):
    """GET sencillo. Devuelve la respuesta solo si es 200, o None."""
    try:
        respuesta = requests.get(url, timeout=timeout, headers={"User-Agent": USER_AGENT})
    except requests.RequestException as err:
        _LOGGER.debug("Fallo de red pidiendo %s: %s", url, err)
        return None

    if respuesta.status_code != 200:
        _LOGGER.debug("%s devolvió HTTP %s", url, respuesta.status_code)
        return None

    return respuesta


def _get_json(url, timeout=15):
    respuesta = _get(url, timeout=timeout)
    if respuesta is None:
        return None
    try:
        return respuesta.json()
    except ValueError:
        _LOGGER.debug("%s no devolvió JSON válido", url)
        return None


# ---------------------------------------------------------------------------
# Token
# ---------------------------------------------------------------------------

def obtener_token(codigo, forzar=False):
    """Devuelve el token del predictor, leyéndolo de la web si hace falta.

    El token es el mismo para cualquier paradero; `codigo` solo sirve para
    pedir una página válida de la que extraerlo.
    """
    if not forzar:
        with _lock:
            if _token["valor"] and time.time() - _token["ts"] < TOKEN_TTL:
                return _token["valor"]

    respuesta = _get(PARADERO_PAGE_URL.format(codigo=codigo))
    if respuesta is None:
        return None

    match = RE_JWT.search(respuesta.text)
    if not match:
        _LOGGER.warning(
            "No se encontró el token en la página de red.cl: es posible que "
            "hayan cambiado la web y haya que actualizar la integración"
        )
        return None

    try:
        valor = base64.b64decode(match.group(1)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        _LOGGER.warning("El token de red.cl no se pudo decodificar")
        return None

    with _lock:
        _token["valor"] = valor
        _token["ts"] = time.time()

    return valor


def invalidar_token():
    """Olvida el token cacheado (p. ej. tras un error de autorización)."""
    with _lock:
        _token["valor"] = None
        _token["ts"] = 0.0


# ---------------------------------------------------------------------------
# Predicción
# ---------------------------------------------------------------------------

def parse_tiempo(texto):
    """Rango de minutos de un texto de llegada, o (None, None).

    red.cl:        'Entre 06 Y 08 min.' -> (6, 8) | 'Mas de 30 min.' -> (30, None)
    Red Regional:  '10 a 14 min'        -> (10, 14) | '+ de 25 min'  -> (25, None)
    Ambos:         'Llegando'           -> (0, 0)
    """
    if not texto:
        return None, None

    limpio = texto.strip()
    if "llegando" in limpio.lower():
        return 0, 0

    match = RE_ENTRE.search(limpio)
    if match:
        return int(match.group(1)), int(match.group(2))

    match = RE_RANGO_A.search(limpio)
    if match:
        return int(match.group(1)), int(match.group(2))

    match = RE_MENOS_DE.search(limpio)
    if match:
        return 0, int(match.group(1))

    match = RE_MAS_DE.search(limpio)
    if match:
        return int(match.group(1)), None

    match = RE_MIN.search(limpio)
    if match:
        minutos = int(match.group(1))
        return minutos, minutos

    return None, None


def clave_linea(linea):
    """Orden natural de líneas: 1A, 1B, 2B, 10B en vez de 10B, 1A, 1B, 2B."""
    match = re.match(r"(\d+)(.*)", linea or "")
    if match:
        return (0, int(match.group(1)), match.group(2).lower())
    return (1, 0, (linea or "").lower())


def _a_entero(valor):
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def _normalizar_servicio(item):
    """Convierte un servicio del predictor a una forma estable y simple."""
    codigo_respuesta = str(item.get("codigorespuesta") or "")
    llegadas = []

    # No miramos el código de respuesta para decidir si hay buses: "00" son
    # dos buses y "01" uno solo, pero pueden aparecer otros. Nos fiamos de
    # qué campos trae: los códigos sin predicción ("10" sin buses hacia el
    # paradero, "11" fuera de horario, "40" parada inhabilitada) los dejan
    # vacíos, y el mensaje de `respuestaServicio` explica el motivo.
    for sufijo in ("1", "2"):
        texto = item.get(f"horaprediccionbus{sufijo}")
        if not texto or not texto.strip():
            continue
        minimo, maximo = parse_tiempo(texto)
        llegadas.append({
            "minutos_min": minimo,
            "minutos_max": maximo,
            "texto": texto.strip(),
            "distancia_m": _a_entero(item.get(f"distanciabus{sufijo}")),
            "patente": (item.get(f"ppubus{sufijo}") or "").strip() or None,
        })

    return {
        "linea": (item.get("servicio") or "").strip(),
        "destino": item.get("destino"),
        "codigo_respuesta": codigo_respuesta,
        "mensaje": (item.get("respuestaServicio") or "").strip(),
        "llegadas": llegadas,
    }


def _normalizar_paradero(datos):
    servicios = datos.get("servicios") or {}
    items = servicios.get("item") or []
    if isinstance(items, dict):  # un solo servicio puede venir sin lista
        items = [items]

    return {
        "codigo": datos.get("paradero"),
        "nombre": datos.get("nomett"),
        "hora_prediccion": datos.get("horaprediccion"),
        "x": datos.get("x"),
        "y": datos.get("y"),
        "servicios": [_normalizar_servicio(item) for item in items],
    }


def consultar_paradero(codigo, intentos=3, espera=1, cache_ttl=PREDICCION_CACHE_TTL):
    """Devuelve las llegadas de un paradero, o None si no se pudo consultar.

    Reintenta igual que la integración de Zaragoza, porque este endpoint
    falla con frecuencia. Si la respuesta no trae paradero, se asume token
    caducado y se renueva antes del siguiente intento.
    """
    codigo = codigo.strip().upper()

    if cache_ttl:
        with _lock:
            cacheado = _cache_prediccion.get(codigo)
        if cacheado and time.time() - cacheado[0] < cache_ttl:
            return cacheado[1]

    forzar_token = False

    for intento in range(intentos):
        token = obtener_token(codigo, forzar=forzar_token)

        if token is not None:
            url = f"{PREDICCION_URL}?t={quote(token, safe='')}&codsimt={quote(codigo, safe='')}"
            datos = _get_json(url)

            if datos and datos.get("nomett"):
                normalizado = _normalizar_paradero(datos)
                if cache_ttl:
                    with _lock:
                        _cache_prediccion[codigo] = (time.time(), normalizado)
                return normalizado

        # Sin token, sin respuesta o respuesta vacía: lo más habitual es que
        # el token haya caducado, así que el siguiente intento lo renueva.
        forzar_token = True
        if intento < intentos - 1:
            time.sleep(espera)

    _LOGGER.debug("No se pudo obtener la predicción del paradero %s", codigo)
    return None


# ---------------------------------------------------------------------------
# Catálogo (sin token): líneas y paraderos de un recorrido
# ---------------------------------------------------------------------------

def listar_servicios():
    """Todos los códigos de línea de Red, p. ej. ['101', '506', 'J10', ...]."""
    datos = _get_json(SERVICIOS_URL)
    if not isinstance(datos, list):
        return []
    return [str(s) for s in datos if s]


def listar_paraderos_de_linea(servicio):
    """Paraderos de una línea, en ambos sentidos.

    Devuelve [{'codigo', 'nombre', 'comuna', 'destino'}], sin duplicados.
    """
    datos = _get_json(RECORRIDO_URL.format(servicio=quote(str(servicio), safe="")))
    if not isinstance(datos, list):
        return []

    paraderos = []
    vistos = set()

    for sentido in datos:
        if not isinstance(sentido, dict):
            continue
        destino = (sentido.get("recorrido") or {}).get("destino") or ""
        for parada in sentido.get("paradas") or []:
            if not isinstance(parada, dict):
                continue
            codigo = parada.get("cod")
            if not codigo or codigo in vistos:
                continue
            vistos.add(codigo)
            paraderos.append({
                "codigo": codigo,
                "nombre": parada.get("name") or "",
                "comuna": parada.get("comuna") or "",
                "destino": destino,
            })

    return paraderos
