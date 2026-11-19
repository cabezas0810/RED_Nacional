"""Config flow: paraderos de RED (Santiago) y de Red Regional (resto de Chile)."""

import re

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from . import api_regional
from .api_utils import (
    clave_linea,
    consultar_paradero,
    listar_paraderos_de_linea,
    listar_servicios,
)
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
    MODO_COMBINADO,
    MODO_POR_LINEA,
    SISTEMA_REGIONAL,
    SISTEMA_SANTIAGO,
)

# Códigos de paradero de RED en Santiago: PA433, PI369, PB1... En regiones
# cada ciudad usa su formato, así que allí se validan contra el GTFS.
RE_CODIGO = re.compile(r"^([A-Z]{1,3})\s*0*(\d{1,5})$", re.IGNORECASE)

MAX_PARADEROS_LISTA = 400
MAX_RESULTADOS_BUSQUEDA = 60
MAX_LINEAS_ETIQUETA = 4

SISTEMA_ETIQUETA_SANTIAGO = "Santiago (RED Movilidad)"
SISTEMA_ETIQUETA_REGIONAL = "Regiones (Red Regional)"

METODO_CODIGO = "Ya sé el código del paradero (PA433, PI369...)"
METODO_LINEA = "Buscar el paradero por línea"

ETIQUETA_COMBINADO = "Próximo y siguiente (cualquier línea)"
ETIQUETA_POR_LINEA = "Una entidad por línea"


def normalizar_codigo(texto):
    """Código de Santiago: 'pa 0433' -> 'PA433'. None si no lo parece."""
    match = RE_CODIGO.match((texto or "").strip())
    if not match:
        return None
    return f"{match.group(1).upper()}{match.group(2)}"


def etiqueta_paradero(paradero):
    """Santiago: 'Avenida Portales esq. La Galaxia (MAIPÚ) [PI369]'."""
    partes = [paradero["nombre"] or paradero["codigo"]]
    if paradero.get("comuna"):
        partes.append(f"({paradero['comuna']})")
    partes.append(f"[{paradero['codigo']}]")
    return " ".join(partes)


def etiqueta_paradero_regional(paradero):
    """Regiones: 'Diego Portales esq. Arturo Prat [1039] · 1A, 1B, 2B, 3A…'.

    Las líneas ayudan a distinguir paraderos homónimos (uno a cada lado de
    la calle) y a saber de un vistazo si es el que buscas.
    """
    etiqueta = f"{paradero['nombre'] or paradero['codigo']} [{paradero['codigo']}]"
    lineas = sorted(paradero.get("lineas", []), key=clave_linea)
    if lineas:
        muestra = ", ".join(lineas[:MAX_LINEAS_ETIQUETA])
        if len(lineas) > MAX_LINEAS_ETIQUETA:
            muestra += "…"
        etiqueta += f" · {muestra}"
    return etiqueta


def lineas_de_entrada(datos):
    """Líneas de un paradero configurado, según su sistema."""
    if datos.get(CONF_SISTEMA) == SISTEMA_REGIONAL:
        return api_regional.lineas_del_paradero(datos[CONF_ZONA_UUID], datos[CONF_CODIGO])
    return lineas_del_paradero(datos[CONF_CODIGO])


def lineas_del_paradero(codigo):
    """Santiago: códigos de línea que pasan por un paradero, según el predictor."""
    datos = consultar_paradero(codigo, intentos=2, cache_ttl=0)
    if datos is None:
        return []
    lineas = {s["linea"] for s in datos.get("servicios", []) if s.get("linea")}
    return sorted(lineas, key=clave_linea)


class RedMovilidadConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Alta de un paradero."""

    VERSION = 1

    def __init__(self):
        self._sistema = SISTEMA_SANTIAGO
        self._zona_uuid = None
        self._zona_nombre = None
        self._zonas = {}
        self._codigo = None
        self._nombre = None
        self._opciones_paraderos = {}

    # -- Elección del sistema -------------------------------------------------

    async def async_step_user(self, user_input=None):
        """Santiago o regiones."""
        if user_input is not None:
            if user_input[CONF_SISTEMA] == SISTEMA_ETIQUETA_REGIONAL:
                self._sistema = SISTEMA_REGIONAL
                return await self.async_step_ciudad()
            self._sistema = SISTEMA_SANTIAGO
            return await self.async_step_santiago()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_SISTEMA, default=SISTEMA_ETIQUETA_SANTIAGO): vol.In(
                    [SISTEMA_ETIQUETA_SANTIAGO, SISTEMA_ETIQUETA_REGIONAL]
                ),
            }),
        )

    # -- Santiago ---------------------------------------------------------------

    async def async_step_santiago(self, user_input=None):
        """Cómo identificar el paradero en Santiago."""
        if user_input is not None:
            if user_input["metodo"] == METODO_LINEA:
                return await self.async_step_buscar_linea()
            return await self.async_step_codigo()

        return self.async_show_form(
            step_id="santiago",
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

    # -- Regiones ---------------------------------------------------------------

    async def async_step_ciudad(self, user_input=None):
        """Ciudad de Red Regional, de la lista que publica el propio servidor."""
        errors = {}

        if user_input is not None and user_input.get("ciudad") in self._zonas:
            self._zona_nombre = user_input["ciudad"]
            self._zona_uuid = self._zonas[self._zona_nombre]
            return await self.async_step_regional_paradero()

        zonas = await self.hass.async_add_executor_job(api_regional.listar_zonas)
        if not zonas:
            errors["base"] = "api_no_disponible"
            return self.async_show_form(
                step_id="ciudad", data_schema=vol.Schema({}), errors=errors
            )

        self._zonas = {z["nombre"]: z["uuid"] for z in zonas}
        return self.async_show_form(
            step_id="ciudad",
            data_schema=vol.Schema({vol.Required("ciudad"): vol.In(list(self._zonas))}),
            errors=errors,
        )

    async def async_step_regional_paradero(self, user_input=None):
        """Código del paradero, o parte de su nombre para buscarlo."""
        errors = {}

        if user_input is not None:
            consulta = user_input["busqueda"].strip()

            # Si es un código exacto de esa ciudad, no hace falta buscar.
            exacto = await self.hass.async_add_executor_job(
                api_regional.buscar_paradero, self._zona_uuid, consulta
            )
            if exacto:
                self._codigo = exacto["codigo"]
                self._nombre = exacto["nombre"] or exacto["codigo"]
                return await self.async_step_linea()

            encontrados = await self.hass.async_add_executor_job(
                api_regional.buscar_paraderos_por_nombre, self._zona_uuid, consulta
            )
            if encontrados is None:
                errors["base"] = "gtfs_no_disponible"
            elif not encontrados:
                errors["base"] = "paradero_no_encontrado"
            elif len(encontrados) > MAX_RESULTADOS_BUSQUEDA:
                errors["base"] = "demasiados_resultados"
            elif len(encontrados) == 1:
                self._codigo = encontrados[0]["codigo"]
                self._nombre = encontrados[0]["nombre"] or encontrados[0]["codigo"]
                return await self.async_step_linea()
            else:
                self._opciones_paraderos = {
                    etiqueta_paradero_regional(p): (p["codigo"], p["nombre"] or p["codigo"])
                    for p in encontrados
                }
                return await self.async_step_regional_resultados()

        return self.async_show_form(
            step_id="regional_paradero",
            data_schema=vol.Schema({vol.Required("busqueda"): str}),
            description_placeholders={"ciudad": self._zona_nombre or ""},
            errors=errors,
        )

    async def async_step_regional_resultados(self, user_input=None):
        """Elegir entre los paraderos que coinciden con la búsqueda."""
        if user_input is not None:
            elegido = self._opciones_paraderos.get(user_input["paradero"])
            if elegido:
                self._codigo, self._nombre = elegido
                return await self.async_step_linea()

        return self.async_show_form(
            step_id="regional_resultados",
            data_schema=vol.Schema({
                vol.Required("paradero"): vol.In(list(self._opciones_paraderos)),
            }),
        )

    # -- Comunes ----------------------------------------------------------------

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
        regional = self._sistema == SISTEMA_REGIONAL

        # El id de Santiago no cambia de formato, para no duplicar paraderos
        # dados de alta antes de existir Red Regional. En regiones incluye la
        # ciudad, porque códigos como "75" pueden repetirse entre ciudades.
        if regional:
            await self.async_set_unique_id(f"{self._zona_uuid}_{self._codigo}_{sufijo}")
        else:
            await self.async_set_unique_id(f"{self._codigo}_{sufijo}")
        self._abort_if_unique_id_configured()

        datos = {
            CONF_SISTEMA: self._sistema,
            CONF_CODIGO: self._codigo,
            CONF_NOMBRE: self._nombre or self._codigo,
            CONF_LINEA: linea,
            CONF_MODO: modo,
        }
        if regional:
            datos[CONF_ZONA_UUID] = self._zona_uuid
            datos[CONF_ZONA_NOMBRE] = self._zona_nombre

        titulo = f"{self._nombre or self._codigo} ({self._codigo})"
        if regional:
            titulo += f" - {self._zona_nombre}"

        if linea:
            titulo += f" - línea {linea}"
        elif modo == MODO_POR_LINEA:
            lineas = await self.hass.async_add_executor_job(lineas_de_entrada, datos)
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
                    lineas_de_entrada, dict(entry.data)
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
