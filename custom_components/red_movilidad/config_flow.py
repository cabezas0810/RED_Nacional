"""Config flow de RED Movilidad (Santiago de Chile)."""

import re

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .api_utils import consultar_paradero, listar_paraderos_de_linea, listar_servicios
from .const import (
    CONF_CODIGO,
    CONF_LINEA,
    CONF_LINEAS,
    CONF_MODO,
    CONF_NOMBRE,
    DOMAIN,
    MODO_COMBINADO,
    MODO_POR_LINEA,
)

# Códigos de paradero de Red: PA433, PI369, PB1, PE24... (letras + número).
RE_CODIGO = re.compile(r"^([A-Z]{1,3})\s*0*(\d{1,5})$", re.IGNORECASE)

MAX_PARADEROS_LISTA = 400

METODO_CODIGO = "Ya sé el código del paradero (PA433, PI369...)"
METODO_LINEA = "Buscar el paradero por línea"

ETIQUETA_COMBINADO = "Próximo y siguiente (cualquier línea)"
ETIQUETA_POR_LINEA = "Una entidad por línea"


def normalizar_codigo(texto):
    """'pa 0433' -> 'PA433'. Devuelve None si no parece un código."""
    match = RE_CODIGO.match((texto or "").strip())
    if not match:
        return None
    return f"{match.group(1).upper()}{match.group(2)}"


def etiqueta_paradero(paradero):
    """'Avenida Portales esq. La Galaxia (MAIPÚ) [PI369]'."""
    partes = [paradero["nombre"] or paradero["codigo"]]
    if paradero.get("comuna"):
        partes.append(f"({paradero['comuna']})")
    partes.append(f"[{paradero['codigo']}]")
    return " ".join(partes)


class RedMovilidadConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Alta de un paradero."""

    VERSION = 1

    def __init__(self):
        self._codigo = None
        self._nombre = None
        self._opciones_paraderos = {}

    async def async_step_user(self, user_input=None):
        """Cómo quiere identificar el paradero."""
        if user_input is not None:
            if user_input["metodo"] == METODO_LINEA:
                return await self.async_step_buscar_linea()
            return await self.async_step_codigo()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("metodo", default=METODO_CODIGO): vol.In(
                    [METODO_CODIGO, METODO_LINEA]
                ),
            }),
        )

    async def async_step_codigo(self, user_input=None):
        """Código del paradero tal cual aparece en la marquesina."""
        errors = {}

        if user_input is not None:
            codigo = normalizar_codigo(user_input[CONF_CODIGO])
            if codigo is None:
                errors["base"] = "codigo_invalido"
            else:
                datos = await self.hass.async_add_executor_job(
                    consultar_paradero, codigo, 2, 1, 0
                )
                if datos is None:
                    errors["base"] = "api_no_disponible"
                else:
                    self._codigo = codigo
                    self._nombre = datos.get("nombre") or codigo
                    return await self.async_step_linea()

        return self.async_show_form(
            step_id="codigo",
            data_schema=vol.Schema({vol.Required(CONF_CODIGO): str}),
            errors=errors,
        )

    async def async_step_buscar_linea(self, user_input=None):
        """Listar los paraderos de una línea para elegir uno."""
        errors = {}

        if user_input is not None:
            servicio = user_input["servicio"].strip().lower()
            servicios = await self.hass.async_add_executor_job(listar_servicios)

            if not servicios:
                errors["base"] = "api_no_disponible"
            elif servicio not in {s.lower() for s in servicios}:
                errors["base"] = "linea_desconocida"
            else:
                paraderos = await self.hass.async_add_executor_job(
                    listar_paraderos_de_linea, servicio
                )
                if not paraderos:
                    errors["base"] = "sin_resultados"
                else:
                    # Las listas largas son incómodas, pero cortarlas dejaría
                    # fuera paraderos reales: mejor mostrarlos todos ordenados
                    # por comuna y nombre.
                    paraderos.sort(key=lambda p: (p.get("comuna", ""), p.get("nombre", "")))
                    self._opciones_paraderos = {
                        etiqueta_paradero(p): (p["codigo"], p["nombre"])
                        for p in paraderos[:MAX_PARADEROS_LISTA]
                    }
                    return await self.async_step_elegir_paradero()

        return self.async_show_form(
            step_id="buscar_linea",
            data_schema=vol.Schema({vol.Required("servicio"): str}),
            errors=errors,
        )

    async def async_step_elegir_paradero(self, user_input=None):
        """Elegir uno de los paraderos de la línea."""
        if user_input is not None:
            elegido = self._opciones_paraderos.get(user_input["paradero"])
            if elegido:
                self._codigo, self._nombre = elegido
                return await self.async_step_linea()

        return self.async_show_form(
            step_id="elegir_paradero",
            data_schema=vol.Schema({
                vol.Required("paradero"): vol.In(list(self._opciones_paraderos)),
            }),
        )

    async def async_step_linea(self, user_input=None):
        """Filtro de línea opcional."""
        if user_input is not None:
            linea = user_input.get(CONF_LINEA, "").strip()
            if linea:
                return await self._crear_entrada(linea=linea, modo=MODO_COMBINADO)
            return await self.async_step_modo()

        return self.async_show_form(
            step_id="linea",
            data_schema=vol.Schema({vol.Optional(CONF_LINEA, default=""): str}),
            description_placeholders={
                "paradero": self._codigo,
                "nombre": self._nombre or "",
            },
        )

    async def async_step_modo(self, user_input=None):
        """Sin línea fija: un par de sensores combinado, o uno por línea."""
        if user_input is not None:
            if user_input[CONF_MODO] == ETIQUETA_POR_LINEA:
                return await self._crear_entrada(linea="", modo=MODO_POR_LINEA)
            return await self._crear_entrada(linea="", modo=MODO_COMBINADO)

        return self.async_show_form(
            step_id="modo",
            data_schema=vol.Schema({
                vol.Required(CONF_MODO, default=ETIQUETA_COMBINADO): vol.In(
                    [ETIQUETA_COMBINADO, ETIQUETA_POR_LINEA]
                ),
            }),
        )

    async def _crear_entrada(self, linea, modo):
        sufijo = linea.upper() if linea else modo
        await self.async_set_unique_id(f"{self._codigo}_{sufijo}")
        self._abort_if_unique_id_configured()

        datos = {
            CONF_CODIGO: self._codigo,
            CONF_NOMBRE: self._nombre or self._codigo,
            CONF_LINEA: linea,
            CONF_MODO: modo,
        }

        titulo = f"{self._nombre or self._codigo} ({self._codigo})"

        if linea:
            titulo += f" - línea {linea}"
        elif modo == MODO_POR_LINEA:
            lineas = await self.hass.async_add_executor_job(
                lineas_del_paradero, self._codigo
            )
            if not lineas:
                # No se pudo consultar: mejor una entrada combinada que una
                # entrada sin ninguna entidad.
                datos[CONF_MODO] = MODO_COMBINADO
            else:
                datos[CONF_LINEAS] = lineas
                titulo += " - todas las líneas"

        return self.async_create_entry(title=titulo, data=datos)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return RedMovilidadOptionsFlow()


def lineas_del_paradero(codigo):
    """Códigos de línea que pasan por un paradero, según el predictor."""
    datos = consultar_paradero(codigo, intentos=2, cache_ttl=0)
    if datos is None:
        return []
    return sorted({s["linea"] for s in datos.get("servicios", []) if s.get("linea")})


class RedMovilidadOptionsFlow(config_entries.OptionsFlow):
    """Cambiar la línea o el modo sin borrar la entrada ni perder historial."""

    async def async_step_init(self, user_input=None):
        entry = self.config_entry

        if user_input is not None:
            linea = user_input.get(CONF_LINEA, "").strip()
            self._nuevos_datos = dict(entry.data)

            if linea:
                self._nuevos_datos.update({CONF_LINEA: linea, CONF_MODO: MODO_COMBINADO})
                self._nuevos_datos.pop(CONF_LINEAS, None)
                return self._guardar()

            return await self.async_step_modo()

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional(CONF_LINEA, default=entry.data.get(CONF_LINEA, "")): str,
            }),
            description_placeholders={
                "paradero": entry.data.get(CONF_CODIGO, ""),
                "nombre": entry.data.get(CONF_NOMBRE, ""),
            },
        )

    async def async_step_modo(self, user_input=None):
        entry = self.config_entry

        if user_input is not None:
            self._nuevos_datos[CONF_LINEA] = ""

            if user_input[CONF_MODO] == ETIQUETA_POR_LINEA:
                lineas = await self.hass.async_add_executor_job(
                    lineas_del_paradero, entry.data[CONF_CODIGO]
                )
                if lineas:
                    self._nuevos_datos.update({CONF_MODO: MODO_POR_LINEA, CONF_LINEAS: lineas})
                else:
                    self._nuevos_datos.update({CONF_MODO: MODO_COMBINADO})
                    self._nuevos_datos.pop(CONF_LINEAS, None)
            else:
                self._nuevos_datos.update({CONF_MODO: MODO_COMBINADO})
                self._nuevos_datos.pop(CONF_LINEAS, None)

            return self._guardar()

        actual = (
            ETIQUETA_POR_LINEA
            if entry.data.get(CONF_MODO) == MODO_POR_LINEA
            else ETIQUETA_COMBINADO
        )
        return self.async_show_form(
            step_id="modo",
            data_schema=vol.Schema({
                vol.Required(CONF_MODO, default=actual): vol.In(
                    [ETIQUETA_COMBINADO, ETIQUETA_POR_LINEA]
                ),
            }),
        )

    def _guardar(self):
        self.hass.config_entries.async_update_entry(self.config_entry, data=self._nuevos_datos)
        return self.async_create_entry(title="", data={})
