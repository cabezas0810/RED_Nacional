"""Sensores de llegada de buses RED en un paradero de Santiago."""

from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo

from .api_utils import consultar_paradero
from .const import (
    CONF_CODIGO,
    CONF_LINEA,
    CONF_LINEAS,
    CONF_MODO,
    CONF_NOMBRE,
    DOMAIN,
    MODO_POR_LINEA,
    SCAN_INTERVAL_SEGUNDOS,
)

SCAN_INTERVAL = timedelta(seconds=SCAN_INTERVAL_SEGUNDOS)


async def async_setup_entry(hass, entry, async_add_entities):
    codigo = entry.data[CONF_CODIGO]
    nombre = entry.data.get(CONF_NOMBRE) or codigo
    modo = entry.data.get(CONF_MODO)
    linea = entry.data.get(CONF_LINEA) or None

    if modo == MODO_POR_LINEA:
        entidades = []
        for linea_paradero in entry.data.get(CONF_LINEAS, []):
            entidades.append(RedBusSensor(codigo, nombre, linea_paradero, 1))
            entidades.append(RedBusSensor(codigo, nombre, linea_paradero, 2))
        # update_before_add: pedimos los datos antes de registrar las
        # entidades. Si no, HA las publica como "desconocido" y espera al
        # siguiente ciclo de sondeo, hasta un minuto en blanco tras el alta
        # y tras cada reinicio. La caché del cliente hace que, de todas las
        # entidades del mismo paradero, solo la primera llegue a la red.
        async_add_entities(entidades, update_before_add=True)
        return

    async_add_entities(
        [
            RedBusSensor(codigo, nombre, linea, 1),
            RedBusSensor(codigo, nombre, linea, 2),
        ],
        update_before_add=True,
    )


class RedBusSensor(SensorEntity):
    """Bus N (1=próximo, 2=siguiente) en un paradero, opcionalmente por línea.

    El estado son los minutos del extremo BAJO de la predicción: red.cl
    devuelve rangos ("Entre 06 Y 08 min."), así que el máximo va en el
    atributo `minutos_max` y el texto literal en `texto_original`.

    Sin filtro de línea, "próximo"/"siguiente" son las dos llegadas más
    cercanas de CUALQUIER línea del paradero, así que la línea de cada una
    puede cambiar entre actualizaciones y va en el atributo `linea` (el
    nombre de una entidad no debe cambiar solo: rompería el historial).
    """

    _attr_icon = "mdi:bus"
    _attr_native_unit_of_measurement = "min"
    _attr_has_entity_name = False

    def __init__(self, codigo, nombre_paradero, linea, numero_bus):
        self._codigo = codigo
        self._nombre_paradero = nombre_paradero
        self._linea = linea
        self._numero_bus = numero_bus
        self._state = None
        self._attrs = {}

        etiqueta = "próximo" if numero_bus == 1 else "siguiente"

        if linea:
            self._attr_name = f"Bus {linea} {etiqueta} - {nombre_paradero}"
            self._attr_unique_id = f"{DOMAIN}_{codigo}_{linea}_{numero_bus}"
        else:
            self._attr_name = f"Bus {etiqueta} - {nombre_paradero}"
            self._attr_unique_id = f"{DOMAIN}_{codigo}_{numero_bus}"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, codigo)},
            name=f"Paradero {codigo} - {nombre_paradero}",
            manufacturer="Red Movilidad",
            model="Paradero",
            configuration_url=(
                f"https://www.red.cl/planifica-tu-viaje/cuando-llega/?codsimt={codigo}"
            ),
        )

    @property
    def native_value(self):
        return self._state

    @property
    def extra_state_attributes(self):
        return self._attrs

    def update(self):
        datos = consultar_paradero(self._codigo)

        if datos is None:
            # El predictor de red.cl falla a menudo, incluso tras reintentar:
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
            (llegada["minutos_min"], servicio, llegada)
            for servicio in servicios
            for llegada in servicio.get("llegadas", [])
            if llegada.get("minutos_min") is not None
        ]
        # Varias líneas empatan a menudo en el extremo bajo del rango
        # ("En menos de 3 min" para dos buses distintos), así que desempatamos
        # por distancia: el bus más cercano es el que llega antes.
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
        self._state = llegada.get("minutos_min")
        self._attrs = self._base_attrs(datos) | {
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

    def _base_attrs(self, datos):
        return {
            "paradero": datos.get("codigo") or self._codigo,
            "nombre_paradero": datos.get("nombre") or self._nombre_paradero,
            "hora_prediccion": datos.get("hora_prediccion"),
        }
