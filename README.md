# **RED Nacional**

Integración **no oficial** para **Home Assistant** que crea sensores en
tiempo real de los buses de Chile: minutos de espera y distancia del bus por paradero y línea.

- **Santiago**: buses de **Red Movilidad** (RED).
- **Regiones**: buses de **Red Regional**, en las 23 ciudades que publica su
  servidor, de Arica a Punta Arenas (Concepción, Valparaíso, Temuco, La
  Serena, Antofagasta, Puerto Montt...).

Es un port de la integración [Zaragoza Tram](https://github.com/jrgim/Zaragoza_tram),
adaptado a las fuentes de datos de Chile.

> ## ⚠️ Antes de instalar: de dónde salen los datos
>
> El Ministerio de Transportes (DTPM) solo publica
> [GTFS estático](https://www.dtpm.cl/index.php/gtfs-vigente) — recorridos y
> horarios programados, **sin tiempo real**. No existe una API oficial
> documentada de predicción de llegadas.
>
> Esta integración usa el **mismo endpoint interno que la web de red.cl**
> (`/predictorPlus/prediccion`), que requiere un token JWT que la propia web
> incrusta en el HTML y caduca cada ~55 minutos. La integración lo obtiene y
> lo renueva sola.
>
> Consecuencias que conviene asumir:
> - **Puede romperse sin aviso** si cambian la web o el endpoint.
> - **No es un servicio contratado**: el intervalo de sondeo es de 60 s a
>   propósito. No lo bajes de forma agresiva ni lo uses para alimentar un
>   servicio público — la instancia pública de otro wrapper de red.cl
>   ([muZk/red-api](https://github.com/muZk/red-api)) tuvo que cerrarse por
>   exceso de peticiones automatizadas.
> - El predictor **falla con frecuencia**; la integración reintenta hasta 3
>   veces y, si no hay respuesta, conserva el último dato conocido.
>
> **En regiones** los datos salen del servidor de la **app móvil Red
> Regional** de la DTPR, que tampoco está documentado. Responde sin token ni
> identificación especial, y la integración se presenta con un `User-Agent`
> propio, sin hacerse pasar por la app oficial. Valen las mismas advertencias,
> con una más: los [términos de la app](https://www.dtpr.cl/terminos) limitan
> su uso a fines personales y prohíben la ingeniería inversa de la app (ver
> [Fuente de los datos](#fuente-de-los-datos-y-condiciones-de-uso)).

## **Índice**

- [Qué sensores crea](#qué-sensores-crea)
- [Instalación](#instalación)
- [Configuración](#configuración)
- [Atributos disponibles](#atributos-disponibles)
- [Comprobar que la API responde](#comprobar-que-la-api-responde)
- [Ejemplos de tarjetas Lovelace](#ejemplos-de-tarjetas-lovelace)
- [Diferencias con la integración de Zaragoza](#diferencias-con-la-integración-de-zaragoza)
- [Fuente de los datos y condiciones de uso](#fuente-de-los-datos-y-condiciones-de-uso)

## **Qué sensores crea**

Por cada paradero configurado obtienes un par de sensores (**próximo** y
**siguiente**). El estado son los **minutos** del extremo bajo de la
predicción, porque red.cl devuelve rangos (`Entre 06 Y 08 min.`); el extremo
alto, la **distancia en metros**, la **patente** del bus y el texto literal
van en los atributos.

Tres configuraciones posibles:

| Configuración | Sensores |
|---|---|
| Línea fija (p. ej. `506`) | 2: próximo y siguiente de esa línea |
| Sin línea, modo combinado | 2: las dos llegadas más próximas de **cualquier** línea del paradero |
| Sin línea, una entidad por línea | 2 por cada línea que pase por el paradero |

En modo combinado, la línea de cada llegada **puede cambiar entre
actualizaciones**, así que va en el atributo `linea` y no en el nombre de la
entidad (cambiar el nombre solo rompería el historial y las automatizaciones).
Si quieres la línea siempre visible, usa "una entidad por línea".

## **Instalación**

### 1. Manual

1. Copia la carpeta `custom_components/red_movilidad` dentro del directorio
   `custom_components` de tu configuración de Home Assistant.
2. Reinicia Home Assistant.

### 2. Usando HACS

1. Añade este repositorio como **repositorio personalizado** en HACS
   (categoría *Integration*).
2. Busca "RED Nacional" e instálalo.
3. Reinicia Home Assistant.

### Icono

La integración trae su propio icono en `custom_components/red_movilidad/brand/`.
Home Assistant lo muestra a partir de la **versión 2026.4**; en versiones
anteriores aparece "icon not available", sin que afecte al funcionamiento.

Es un diseño original: no usa el logo de RED, de Red Regional ni de Home
Assistant. Para cambiar sus colores, edítalos al principio de
`scripts/generar_icono.py` y ejecútalo (necesita Pillow):

```bash
python3 scripts/generar_icono.py
```

## **Configuración**

**Ajustes** → **Dispositivos y servicios** → **+ Añadir integración** → "RED Nacional". Primero eliges **Santiago** o **Regiones**.

### Santiago

Eliges cómo identificar el paradero:

- **Ya sé el código del paradero**: escribe el código de la marquesina o de la
  app Red (`PA433`, `PI369`). Se valida contra red.cl y se usa el nombre real
  del paradero para nombrar las entidades.
- **Buscar el paradero por línea**: escribe la línea (`506`, `J10`, `210`) y
  elige el paradero de su recorrido, con nombre y comuna. Esta búsqueda usa
  `restservice_v2/rest/getrecorrido`, que no necesita token.

### Regiones

1. Eliges la **ciudad**, de la lista que publica el propio servidor.
2. Escribes el **código del paradero** tal como aparece en la app Red Regional
   o **parte de su nombre**. Cada ciudad usa su propio formato de código
   (`1039` en Temuco, `P44723` en Concepción, `PF-175` en Arica,
   `PR-V-147` en Valparaíso), así que no se valida con un patrón sino contra
   la lista de paraderos de la ciudad.
3. Si buscaste por nombre, eliges entre los resultados. Basta con que
   aparezcan todas las palabras, en cualquier orden y sin importar tildes:
   como los paraderos se llaman por cruces de calles, `portales prat`
   encuentra "Diego Portales esq. Arturo Prat". Junto a cada resultado salen
   algunas de sus líneas, para distinguir los paraderos con el mismo nombre
   (uno a cada lado de la calle).

La lista de paraderos, líneas y destinos de cada ciudad es un GTFS de entre 30
y 400 KB que la integración descarga una vez y solo vuelve a bajar cuando
cambia de versión.

### En ambos casos

Después, opcionalmente, filtras por línea. Si la dejas en blanco eliges entre
modo combinado y una entidad por línea.

Un mismo paradero puede tener varias entradas (por ejemplo, una por línea),
pero **dos entradas no pueden compartir línea**: una de "todas las líneas" ya
incluye los sensores de cada línea. El formulario lo impide y te dice qué
entrada los tiene. Si te quedó un caso así de una versión anterior, aparece
un aviso en *Ajustes → Reparaciones*.

### Cambiar línea o modo sin recrear la integración

Cada entrada tiene botón **Configurar** (⚙️) para cambiar la línea filtrada o
alternar entre "combinado" y "una entidad por línea", sin borrar la
integración ni perder el historial de las entidades que no cambian.

## **Atributos disponibles**

```yaml
paradero: PA433
nombre_paradero: PARADA 1 / ESCUELA DE INGENIERÍA
hora_prediccion: "12:54"
linea: "507"
destino: Av. Grecia
minutos_min: 3
minutos_max: 7
distancia_m: 1341
distancia_km: 1.34
patente: TBFW-81
texto_original: Entre 3 Y 7 min
estado_servicio: Informacion de tiempos de los proximos 2 buses
```

### Códigos de respuesta de red.cl

El predictor no está documentado; estos son los `codigorespuesta` observados
en consultas reales, y que la integración expone en `estado_servicio`:

| Código | Significado |
|---|---|
| `00` | Tiempos de los dos próximos buses |
| `01` | Tiempo de un solo bus (el segundo viene vacío) |
| `10` | No hay buses que se dirijan al paradero |
| `11` | Servicio fuera de horario de operación |
| `40` | Parada inhabilitada (el mensaje indica el paradero alternativo) |

La integración **no** decide por el código si hay buses: mira si vienen los
campos de predicción. Así, si aparece un código nuevo que sí trae tiempos,
sigue funcionando.

En modo combinado, cuando dos líneas empatan en el extremo bajo del rango
(muy habitual con "En menos de 3 min"), se ordena por **distancia**: el bus
más cercano se considera el próximo.

### Atributos extra en regiones

```yaml
hora_llegada: "2026-11-19T21:49:12+00:00"   # hora exacta estimada
tiempo_real: true                           # false = horario programado
```

**El estado se calcula distinto según el sistema.** red.cl solo da un rango
("Entre 06 Y 08 min."), así que en Santiago el estado es su extremo bajo. Red
Regional da además una hora exacta, así que en regiones el estado son los
minutos hasta esa hora. En ambos casos el rango está en `minutos_min` y
`minutos_max`.

## **Comprobar que la API responde**

Antes de culpar a Home Assistant, prueba la fuente directamente:

```bash
python3 scripts/probar_api.py PA433
```

Imprime si el token se obtuvo y, línea por línea, los dos próximos buses con
tiempo, distancia y patente. Con un segundo argumento filtra por línea
(`python3 scripts/probar_api.py PA433 506`).

Para regiones:

```bash
python3 scripts/probar_api.py --ciudades
python3 scripts/probar_api.py --ciudad Temuco --buscar "portales prat"
python3 scripts/probar_api.py --ciudad Temuco 1039 1A
```

Para comprobar el parseo sin tocar la red:

```bash
python3 scripts/test_parseo.py
python3 scripts/test_regional.py
```

## **Ejemplos de tarjetas Lovelace**

Requieren [Mushroom Cards](https://github.com/piitaya/lovelace-mushroom) o
[button-card](https://github.com/custom-cards/button-card) desde HACS.

### Mushroom: tiempo y distancia (modo combinado)

En modo combinado la línea cambia entre actualizaciones, así que se muestra
con una `mushroom-template-card` leyendo el atributo `linea`.

```yaml
type: vertical-stack
cards:
  - type: custom:mushroom-title-card
    title: 🚌 Escuela de Ingeniería
    subtitle: Paradero PA433
  - type: horizontal-stack
    cards:
      - type: custom:mushroom-template-card
        entity: sensor.bus_proximo_parada_1_escuela_de_ingenieria
        primary: "Línea {{ state_attr(entity, 'linea') }}"
        secondary: >-
          {{ states(entity) }} min · {{ state_attr(entity, 'distancia_km') }} km
        icon: mdi:bus
        icon_color: green
        layout: vertical
        tap_action:
          action: more-info
      - type: custom:mushroom-template-card
        entity: sensor.bus_siguiente_parada_1_escuela_de_ingenieria
        primary: "Línea {{ state_attr(entity, 'linea') }}"
        secondary: >-
          {{ states(entity) }} min · {{ state_attr(entity, 'distancia_km') }} km
        icon: mdi:bus
        icon_color: blue
        layout: vertical
        tap_action:
          action: more-info
```

### button-card: rango de llegada y hora estimada (línea fija)

```yaml
type: custom:button-card
entity: sensor.bus_507_proximo_parada_1_escuela_de_ingenieria
name: Línea 507
icon: mdi:bus
show_state: true
show_label: true
state_display: |
  [[[
    var min = entity.attributes.minutos_min;
    var max = entity.attributes.minutos_max;
    if (min === null || min === undefined) return "Sin datos";
    if (max === null || max === undefined) return "+" + min + " min";
    return (min === max) ? min + " min" : min + "-" + max + " min";
  ]]]
label: |
  [[[
    var d = entity.attributes.distancia_km;
    var p = entity.attributes.patente;
    if (d === null || d === undefined) return "Sin datos";
    return d + " km" + (p ? " · " + p : "");
  ]]]
styles:
  card:
    - background: "linear-gradient(120deg, #c8102e 80%, #ef9a9a 100%)"
    - color: white
    - font-weight: bold
    - border-radius: 20px
    - padding: 20px
  icon:
    - color: white
    - width: 48px
    - animation: >
        [[[ return (entity.state < 5) ? "bounce 1s infinite" : "none"; ]]]
  state:
    - font-size: 28px
  label:
    - font-size: 15px
    - color: "#ffebee"
extra_styles: |
  @keyframes bounce {
    0%, 100% { transform: translateY(0);}
    50% { transform: translateY(-10px);}
  }
tap_action:
  action: more-info
```

## **Diferencias con la integración de Zaragoza**

| | Zaragoza Tram | Santiago (RED) | Regiones (Red Regional) |
|---|---|---|---|
| Fuente | API abierta del Ayuntamiento, documentada | Endpoint interno de red.cl, no documentado | Servidor de la app Red Regional, no documentado |
| Autenticación | ninguna | token JWT leído de la web, caduca ~55 min | ninguna |
| Modos tranvía/bus | sí | solo bus (Metro no usa el predictor) | solo bus |
| Selección de parada | lista fija embebida + listado de postes | código validado en vivo, o búsqueda por línea | ciudad, y luego código o búsqueda por nombre en el GTFS |
| Estado del sensor | minutos exactos | minutos del extremo bajo del rango | minutos hasta la hora exacta estimada |
| Distancia del vehículo | no la expone la API | sí, en metros y km | sí, en metros y km |
| Patente del bus | — | sí, cuando red.cl la entrega | sí |

## **Fuente de los datos y condiciones de uso**

Los datos de llegada proceden de **Red Movilidad** (www.red.cl) y son
propiedad del **Directorio de Transporte Público Metropolitano (DTPM)**,
Ministerio de Transportes y Telecomunicaciones de Chile. Esta integración
solo los consulta y los muestra tal cual los entrega el servicio.

Según las [condiciones de uso y privacidad de red.cl](https://www.red.cl/condiciones-de-uso-y-privacidad/),
conviene tener presente que:

- Los contenidos **no pueden usarse con fines comerciales o de lucro de
  ninguna clase**.
- Al usar la información hay que **citar la fuente**.
- El DTPM puede modificar esas condiciones en cualquier momento.

Por eso, aunque el código de esta integración es MIT y su licencia permite el
uso comercial, **esa licencia cubre el código, no los datos**. Quien instale
la integración queda sujeto a las condiciones del DTPM respecto a la
información que obtiene.

En el momento de escribir esto, el `robots.txt` de red.cl no restringe
ninguna ruta y sus condiciones no mencionan el acceso automatizado, el
scraping ni límites de peticiones. Aun así, el intervalo de sondeo por
defecto es de 60 s a propósito, y **no conviene** desplegar instancias
públicas que concentren el tráfico de mucha gente: es lo que obligó a cerrar
la instancia pública de [muZk/red-api](https://github.com/muZk/red-api).

Consultas sobre el uso de los contenidos: `comunicaciones@dtpm.gob.cl`.

### Red Regional (regiones)

Los datos de regiones proceden de la **app Red Regional**, de la **División
de Transporte Público Regional (DTPR)** del Ministerio de Transportes y
Telecomunicaciones. Las posiciones salen del GPS que deben llevar los buses
de los perímetros de exclusión, y las predicciones las calcula el servidor de
la app.

Según los [términos de la app](https://www.dtpr.cl/terminos):

- El uso es **estrictamente personal**.
- Se prohíbe la **comercialización o distribución** de sus contenidos.
- Se prohíbe **descompilar, descifrar o alterar la aplicación**.
- La DTPR puede retirar el acceso ante incumplimientos y modificar los
  términos en cualquier momento.

Esta integración no descompila ni modifica la app: consulta por HTTP un
servidor que responde a peticiones normales, con un `User-Agent` propio, y
no envía las cabeceras ni identificadores con que se identifica la app
oficial. Aun así, ese servidor no es una API pública, así que **úsala solo
para fines personales** y asume que puede dejar de funcionar sin aviso.

La integración ignora a propósito los **reportes de usuarios** que el
servidor incluye junto a las predicciones (por ejemplo, "Paradero en buen
estado"): no son avisos del servicio.

## **Licencia**

MIT. Ver [LICENSE](LICENSE).

Este proyecto es un port de [Zaragoza Tram](https://github.com/jrgim/Zaragoza_tram)
de jrgim, también bajo licencia MIT. La licencia conserva el aviso de
copyright del proyecto original junto al de este port.
