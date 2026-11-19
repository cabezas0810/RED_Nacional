# **RED Movilidad Santiago**

Integración para **Home Assistant** que crea sensores en tiempo real de los
buses de **Red Movilidad** (Santiago de Chile): minutos de espera y distancia
del bus por paradero y línea.

Es un port de la integración [Zaragoza Tram](https://github.com/jrgim/Zaragoza_tram),
adaptado a la fuente de datos de Santiago.

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

## **Índice**

- [Qué sensores crea](#qué-sensores-crea)
- [Instalación](#instalación)
- [Configuración](#configuración)
- [Atributos disponibles](#atributos-disponibles)
- [Comprobar que la API responde](#comprobar-que-la-api-responde)
- [Ejemplos de tarjetas Lovelace](#ejemplos-de-tarjetas-lovelace)
- [Diferencias con la integración de Zaragoza](#diferencias-con-la-integración-de-zaragoza)

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
2. Busca "RED Movilidad Santiago" e instálalo.
3. Reinicia Home Assistant.

## **Configuración**

**Ajustes** → **Dispositivos y servicios** → **+ Añadir integración** → "RED
Movilidad". Primero eliges cómo identificar el paradero:

- **Ya sé el código del paradero**: escribe el código de la marquesina o de la
  app Red (`PA433`, `PI369`). Se valida contra red.cl y se usa el nombre real
  del paradero para nombrar las entidades.
- **Buscar el paradero por línea**: escribe la línea (`506`, `J10`, `210`) y
  elige el paradero de su recorrido, con nombre y comuna. Esta búsqueda usa
  `restservice_v2/rest/getrecorrido`, que no necesita token.

Después, opcionalmente, filtras por línea. Si la dejas en blanco eliges entre
modo combinado y una entidad por línea.

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

## **Comprobar que la API responde**

Antes de culpar a Home Assistant, prueba la fuente directamente:

```bash
python3 scripts/probar_api.py PA433
```

Imprime si el token se obtuvo y, línea por línea, los dos próximos buses con
tiempo, distancia y patente. Con un segundo argumento filtra por línea
(`python3 scripts/probar_api.py PA433 506`).

Para comprobar el parseo sin tocar la red:

```bash
python3 scripts/test_parseo.py
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

| | Zaragoza Tram | RED Movilidad Santiago |
|---|---|---|
| Fuente | API abierta del Ayuntamiento, documentada | Endpoint interno de red.cl, no documentado |
| Autenticación | ninguna | token JWT leído de la web, caduca ~55 min |
| Modos tranvía/bus | sí | solo bus (Metro no usa el predictor) |
| Selección de parada | lista fija embebida + listado de postes | código validado en vivo, o búsqueda por línea |
| Estado del sensor | minutos exactos | minutos del extremo bajo del rango |
| Distancia del vehículo | no la expone la API | sí, en metros y km |
| Patente del bus | — | sí, cuando red.cl la entrega |

## **Licencia**

MIT. Ver [LICENSE](LICENSE).
