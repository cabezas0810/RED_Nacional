"""Constantes de la integración RED Movilidad (Santiago de Chile)."""

DOMAIN = "red_movilidad"

# ---------------------------------------------------------------------------
# Endpoints de red.cl
#
# IMPORTANTE: ninguno de estos es una API oficial documentada. Son los mismos
# endpoints que usa la web de Red Movilidad (www.red.cl), así que pueden
# cambiar o dejar de funcionar sin previo aviso. El DTPM solo publica GTFS
# estático (sin tiempo real), por eso no hay una alternativa "oficial".
# ---------------------------------------------------------------------------

# Página del paradero. Solo se usa para leer el token JWT que la propia web
# incrusta en el HTML: no hay registro ni API key, el token caduca (~55 min).
PARADERO_PAGE_URL = "https://www.red.cl/planifica-tu-viaje/cuando-llega/?codsimt={codigo}"

# Predicción de llegadas. Requiere el token anterior en el parámetro "t".
PREDICCION_URL = "https://www.red.cl/predictorPlus/prediccion"

# Listado de todos los códigos de servicio (línea). No requiere token.
SERVICIOS_URL = "https://www.red.cl/restservice_v2/rest/getservicios/all"

# Detalle de un recorrido, incluyendo sus paraderos. No requiere token.
# Se usa para poder buscar un paradero por línea en el config flow.
RECORRIDO_URL = "https://www.red.cl/restservice_v2/rest/getrecorrido/{servicio}"

# Identificación honesta del cliente (no suplantamos un navegador).
USER_AGENT = "HomeAssistant-RedMovilidad/0.1.0"

# El token dura ~55 min según la propia web; lo renovamos antes por margen.
TOKEN_TTL = 50 * 60

# Varios sensores comparten paradero (próximo/siguiente, o uno por línea):
# con esta caché solo el primero del ciclo hace la petición real.
PREDICCION_CACHE_TTL = 25

# Intervalo de sondeo. Conservador a propósito: el endpoint no es público y
# conviene no castigarlo (la instancia pública de otro wrapper se cayó por
# exceso de peticiones automatizadas).
SCAN_INTERVAL_SEGUNDOS = 60

# Claves de configuración
CONF_CODIGO = "codigo"
CONF_NOMBRE = "nombre"
CONF_LINEA = "linea"
CONF_MODO = "modo"
CONF_LINEAS = "lineas"

MODO_COMBINADO = "combinado"
MODO_POR_LINEA = "por_linea"
