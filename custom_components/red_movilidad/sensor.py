"""Sensores de llegada de buses: RED (Santiago) y Red Regional (resto de Chile)."""

from datetime import timedelta
from functools import partial

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from . import api_regional
from .api_utils import consultar_paradero
from .const import (
    CONF_CODIGO,
    CONF_LINEA,
    CONF_LINEAS,
    CONF_MODO,
    CONF_NOMBRE,
    CONF_SISTEMA,
    CONF_ZONA_NOMBRE,
    CONF_ZONA_UUID,
    DOMAIN,
    MODO_POR_LINEA,
    SCAN_INTERVAL_SEGUNDOS,
    SISTEMA_REGIONAL,
)

SCAN_INTERVAL = timedelta(seconds=SCAN_INTERVAL_SEGUNDOS)


def _origen(entry):
    """Cómo consultar el paradero, prefijo de ids y dispositivo, según el sistema.

    Santiago conserva exactamente sus ids de siempre, para que las entidades
    creadas antes de existir Red Regional no cambien ni pierdan historial.
    """
    datos = entry.data
    codigo = datos[CONF_CODIGO]
    nombre = datos.get(CONF_NOMBRE) or codigo

    if datos.get(CONF_SISTEMA) == SISTEMA_REGIONAL:
        zona_uuid = datos[CONF_ZONA_UUID]
        ciudad = datos.get(CONF_ZONA_NOMBRE) or ""
        consultar = partial(api_regional.consultar_paradero, zona_uuid, codigo)
        prefijo = f"{DOMAIN}_{zona_uuid}_{codigo}"
        dispositivo = DeviceInfo(
            identifiers={(DOMAIN, f"{zona_uuid}_{codigo}")},
            name=f"Paradero {codigo} - {nombre} ({ciudad})",
            manufacturer="Red Regional (DTPR)",
            model="Paradero",
        )
        return consultar, prefijo, dispositivo

    consultar = partial(consultar_paradero, codigo)
    prefijo = f"{DOMAIN}_{codigo}"
    dispositivo = DeviceInfo(
        identifiers={(DOMAIN, codigo)},
        name=f"Paradero {codigo} - {nombre}",
        manufacturer="Red Movilidad",
        model="Paradero",
        configuration_url=(
            f"https://www.red.cl/planifica-tu-viaje/cuando-llega/?codsimt={codigo}"
        ),
    )
    return consultar, prefijo, dispositivo


async def async_setup_entry(hass, entry, async_add_entities):
    codigo = entry.data[CONF_CODIGO]
    nombre = entry.data.get(CONF_NOMBRE) or codigo
    modo = entry.data.get(CONF_MODO)
    linea = entry.data.get(CONF_LINEA) or None
    consultar, prefijo, dispositivo = _origen(entry)

    def sensor(linea_sensor, numero):
        return RedBusSensor(
            codigo, nombre, linea_sensor, numero, consultar, prefijo, dispositivo
        )

    if modo == MODO_POR_LINEA:
        entidades = []
        for linea_paradero in entry.data.get(CONF_LINEAS, []):
            entidades.append(sensor(linea_paradero, 1))
            entidades.append(sensor(linea_paradero, 2))
    else:
        entidades = [sensor(linea, 1), sensor(linea, 2)]

    # update_before_add: pedimos los datos antes de registrar las
    # entidades. Si no, HA las publica como "desconocido" y espera al
    # siguiente ciclo de sondeo, hasta un minuto en blanco tras el alta
    # y tras cada reinicio. La caché del cliente hace que, de todas las
    # entidades del mismo paradero, solo la primera llegue a la red.
    async_add_entities(entidades, update_before_add=True)


def _minutos(llegada):
    """Minutos hasta la llegada.

    Red Regional da una hora exacta, de la que el cliente calcula `minutos`.
    red.cl solo da un rango, así que allí se usa su extremo bajo.
    """
    minutos = llegada.get("minutos")
    return minutos if minutos is not None else llegada.get("minutos_min")


class RedBusSensor(SensorEntity):
    """Bus N (1=próximo, 2=siguiente) en un paradero, opcionalmente por línea.

    El estado son los minutos que faltan. En Santiago, red.cl devuelve rangos
    ("Entre 06 Y 08 min.") y el estado es su extremo bajo; en regiones viene
    una hora exacta y el estado se calcula a partir de ella. En ambos casos
    el rango va en `minutos_min`/`minutos_max` y el texto en `texto_original`.

    Sin filtro de línea, "próximo"/"siguiente" son las dos llegadas más
    cercanas de CUALQUIER línea del paradero, así que la línea de cada una
    puede cambiar entre actualizaciones y va en el atributo `linea` (el
    nombre de una entidad no debe cambiar solo: rompería el historial).
    """

    _attr_icon = "mdi:bus"
    _attr_native_unit_of_measurement = "min"
    _attr_has_entity_name = False

    def __init__(
        self, codigo, nombre_paradero, linea, numero_bus, consultar, prefijo, dispositivo
    ):
        self._codigo = codigo
        self._nombre_paradero = nombre_paradero
        self._linea = linea
        self._numero_bus = numero_bus
        self._consultar = consultar
        self._state = None
        self._attrs = {}

        etiqueta = "próximo" if numero_bus == 1 else "siguiente"

        if linea:
            self._attr_name = f"Bus {linea} {etiqueta} - {nombre_paradero}"
            self._attr_unique_id = f"{prefijo}_{linea}_{numero_bus}"
        else:
            self._attr_name = f"Bus {etiqueta} - {nombre_paradero}"
            self._attr_unique_id = f"{prefijo}_{numero_bus}"

        self._attr_device_info = dispositivo

    @property
    def native_value(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return self._attrs

    def update(self):
        datos = self._consultar()

        if datos is None:
            # Los servidores fallan a menudo, incluso tras reintentar:
            # conservamos el último dato conocido en vez de vaciar el sensor.
            return

        servicios = datos.get("servicios", [])

        if self._linea:
            self._actualizar_con_linea(datos, servicios)
        else:
            self._actualizar_sin_linea(datos, servicios)

    def _actualizar_con_linea(self, datos, servicios):
        objetivo = self._linea.lower()
        servicio = next(
            (s for s in servicios if (s.get("linea") or "").lower() == objetivo), None
        )

        if servicio is None:
            self._state = None
            self._attrs = self._base_attrs(datos) | {"estado_servicio": "Línea sin datos"}
            return

        llegadas = servicio.get("llegadas", [])
        if len(llegadas) < self._numero_bus:
            self._state = None
            self._attrs = self._base_attrs(datos) | {
                "linea": servicio.get("linea"),
                "destino": servicio.get("destino"),
                "estado_servicio": servicio.get("mensaje") or "Sin buses estimados",
            }
            return

        self._aplicar(datos, servicio, llegadas[self._numero_bus - 1])

    def _actualizar_sin_linea(self, datos, servicios):
        candidatas = [
            (_minutos(llegada), servicio, llegada)
            for servicio in servicios
            for llegada in servicio.get("llegadas", [])
            if _minutos(llegada) is not None
        ]
        # Varias líneas empatan a menudo en los minutos ("En menos de 3 min"
        # para dos buses distintos), así que desempatamos por distancia: el
        # bus más cercano es el que llega antes.
        candidatas.sort(key=lambda item: (item[0], item[2].get("distancia_m") or 10**9))

        if len(candidatas) < self._numero_bus:
            self._state = None
            self._attrs = self._base_attrs(datos) | {
                "estado_servicio": "Sin buses estimados"
            }
            return

        _, servicio, llegada = candidatas[self._numero_bus - 1]
        self._aplicar(datos, servicio, llegada)

    def _aplicar(self, datos, servicio, llegada):
        self._state = _minutos(llegada)
        atributos = self._base_attrs(datos) | {
            "linea": servicio.get("linea"),
            "destino": servicio.get("destino"),
            "minutos_min": llegada.get("minutos_min"),
            "minutos_max": llegada.get("minutos_max"),
            "distancia_m": llegada.get("distancia_m"),
            "distancia_km": (
                round(llegada["distancia_m"] / 1000, 2)
                if llegada.get("distancia_m") is not None
                else None
            ),
            "patente": llegada.get("patente"),
            "texto_original": llegada.get("texto"),
            "estado_servicio": servicio.get("mensaje"),
        }
        # Solo Red Regional trae hora exacta y si la predicción es en vivo.
        for clave in ("hora_llegada", "tiempo_real"):
            if clave in llegada:
                atributos[clave] = llegada[clave]
        self._attrs = atributos

    def _base_attrs(self, datos):
        return {
            "paradero": datos.get("codigo") or self._codigo,
            "nombre_paradero": datos.get("nombre") or self._nombre_paradero,
            "hora_prediccion": datos.get("hora_prediccion"),
        }
