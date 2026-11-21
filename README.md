# EPG - Guia Electronica de Programacion (TV España)

[![Netlify Status](https://api.netlify.com/api/v1/badges/ca6936cb-f26f-4be2-b332-d9e872601737/deploy-status)](https://app.netlify.com/projects/epg-spain/deploys)
[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?logo=githubactions&logoColor=white)](https://github.com/hectorzin/epg/actions)
[![Node.js](https://img.shields.io/badge/Node.js_22-339933?logo=nodedotjs&logoColor=white)](https://nodejs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)](https://react.dev/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-38B2AC?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![XMLTV](https://img.shields.io/badge/XMLTV-format-orange)](https://wiki.xmltv.org/)

Fork simplificado de [iptv-org/epg](https://github.com/iptv-org/epg) para descargar la EPG de canales de television en España y generar una guia nacional arabe.

### 🌐 [Dashboard en vivo](https://epg-spain.netlify.app/) · [Guía global](https://raw.githubusercontent.com/hectorzin/epg/main/guides/guide.xml.gz) · [España](https://raw.githubusercontent.com/hectorzin/epg/main/guides/guide-es.xml) · [Francia](https://raw.githubusercontent.com/hectorzin/epg/main/guides/guide-fr.xml) · [Reino Unido](https://raw.githubusercontent.com/hectorzin/epg/main/guides/guide-gb.xml)

## Dashboard web

El proyecto incluye un dashboard web completo construido con React, TypeScript y Tailwind CSS:

| Funcionalidad | Descripcion |
| --- | --- |
| **Dashboard** | Metricas clave: canales, programas, cobertura, desglose por fuente, top categorias, densidad horaria |
| **Guia TV** | Parrilla tipo Movistar+ agrupada por categorias (grupos plegables, refresco cada 5 min) y timeline interactivo de 48h, con filtro por fuente, busqueda y detalle de cada programa |
| **Canales** | Listado de los 183 canales agrupados por fuente, con busqueda e indicador de emision actual |
| **Info** | Fuentes de datos, horario de actualizacion, reproductores compatibles, enlaces utiles |

La **Guia TV** abre por defecto en una parrilla al estilo Movistar+: una tarjeta por canal con logo, barra de progreso, programa en emision, episodio y horario. Los canales se agrupan y ordenan segun una lista M3U privada (ver [Lineup de la Guia TV](#lineup-de-la-guia-tv)):

- Los grupos se contraen y expanden pulsando su titulo, y el estado se guarda en el navegador.
- La vista de linea de tiempo sigue disponible con el selector de vista (`#/guide?vista=timeline`).
- Mientras la Guia TV esta abierta, los datos se refrescan cada 5 minutos.

El dashboard se despliega en Netlify y carga la guía publicada en GitHub.

## Fuentes soportadas

| Fuente | Canales | Metodo |
| --- | --- | --- |
| `movistarplus.es` | 160 | Scraping HTML |
| `programacion-tv.elpais.com` | 17 | API JSON |
| `orangetv.orange.es` | 6 | API JSON |

El repositorio también publica `guides/guide-arabic.xml`, generado con los catálogos árabes de Shahid,
elCinema, OSN, beIN, beIN SPORTS MENA, Al Jazeera, ART y Ayn. Shahid se procesa primero; las
demás fuentes completan canales que aún no tienen programación. SAT.tv y EPGShare01 se excluyen
porque las pruebas no devolvieron programación utilizable. La guía cubre dos días y elCinema
trabaja con una conexión y un segundo de demora entre peticiones. Laâyoune y Tamazight se añaden
desde la parrilla pública de SNRT. Marruecos, Argelia y Túnez no tienen guía nacional propia.

> Los canales estan definidos en `sites/movistarplus.es/movistarplus.es.channels.xml`. Este fichero incluye canales de las 3 fuentes (cada canal tiene el atributo `site` indicando de donde se obtienen sus datos).

## Como funciona

1. El workflow orquestador (`epg-orchestrator.yml`) se ejecuta cada día a las 03:00 UTC (o manualmente).
2. Lanza en paralelo los generadores nacionales (`generate-es.yml`, `generate-fr.yml`, `generate-arabic.yml`, `generate-gb.yml`, `generate-pt.yml`, `generate-nl.yml`, `generate-it.yml`, `generate-de.yml`, `generate-tr.yml`, `generate-be.yml`, `generate-ca.yml` y `generate-af.yml`). Cada uno publica su guía nacional.
3. España lee el fichero maestro, ejecuta sus parsers, enriquece el XMLTV con la capa Xtream (`scripts/process-epg.py`, `epg/aliases.json`, `epg/xtream-aliases.json`) y publica `guides/guide-es.xml`.
4. Francia genera `guides/guide-fr.xml` (SFR, Canal+, Telecablesat) y aplica la misma capa con `epg/aliases-fr.json` y `epg/xtream-aliases-fr.json` antes de publicar. Países Bajos y Bélgica leen esa guía ya publicada.
5. Arabic genera `guides/guide-arabic.xml`, añade Laâyoune y Tamazight con `scripts/grab_snrt.py` y aplica `epg/aliases-arabic.json` y `epg/xtream-aliases-arabic.json`.
6. Reino Unido genera `guides/guide-gb.xml` fusionando EPGShare UK1, Sky, tv24.co.uk y Virgin TV Go con `scripts/gb-epg.py`, reescribe colisiones de ID con otras regiones a `@UK` y aplica `epg/aliases-gb.json` y `epg/xtream-aliases-gb.json`.
7. Portugal genera `guides/guide-pt.xml` con `scripts/pt-epg.py` (NOS, MEO, Vodafone, TVI; dos días) y aplica `epg/aliases-pt.json` y `epg/xtream-aliases-pt.json`.
8. Países Bajos publica `guides/guide-nl.xml` y, al elegir canales, consulta `guides/guide-es.xml`, `guides/guide-fr.xml`, `guides/guide-arabic.xml`, `guides/guide-gb.xml` y `guides/guide-pt.xml`.
9. Bélgica publica `guides/guide-be.xml`. Antes de descargar, lee las guías nacionales ya publicadas en `guides/`, en particular `guides/guide-fr.xml` y `guides/guide-nl.xml`. Si un id ya tiene programas en una de ellas, no vuelve a descargar esa parrilla.
10. Canadá publica `guides/guide-ca.xml` con `scripts/ca-epg.py`. Antes de descargar, lee las guías nacionales ya publicadas. TV Hebdo cubre los canales franceses; EPGShare CA2 aporta el corte regional en inglés y francés; open-epg solo rellena feeds que CA2 no separa. Si un id ya tiene programas, no se vuelve a descargar: `LoveNature.ca@SD` permanece en la guía neerlandesa. No se mezclan ciudades, TSN, Sportsnet ni las franjas este/oeste.
11. África publica `guides/guide-af.xml` con `scripts/af-epg.py`. Antes de descargar, lee las guías nacionales ya publicadas, en particular Francia, Portugal, Reino Unido y la guía árabe. Canal+ Afrique aporta la parrilla de las señales que aún no tienen programas; TMA Caraïbes aporta su único canal. Si un id ya tiene programas, no se vuelve a descargar. TVC News Nigeria reutiliza la señal ya publicada en la guía británica. RTS Senegal no reutiliza RTS Suiza, ORTM 2 no reutiliza ORTM 1, y Al Jazeera árabe no reutiliza Al Jazeera English.
12. Cuando terminan los generadores (incluso si uno falla), el orquestador hace checkout de `main`, fusiona los ficheros de `guides/` con `scripts/merge-national-guides.py` en un XML temporal, lo valida, lo comprime con GZIP nivel 9 y `mtime=0` y publica una sola vez `guides/guide.xml.gz` tras comprobar que al descomprimirlo el XML es idéntico. El `guide.xml` global sin comprimir se elimina del repositorio. La fusión conserva **todos** los canales (IDs, `display-name`, alias y clones Xtream) de cada guía nacional, pero **recorta la parrilla global** a **hoy y mañana** según `Europe/Madrid`, respetando las zonas horarias XMLTV y manteniendo cualquier programa que solape ese intervalo. En la guía global únicamente, los programas que **empiezan** mañana (fecha de inicio en Madrid) dejan fuera descripciones, iconos y demás metadatos secundarios del `<programme>` (se conservan `title`, `category` y atributos `channel`/`start`/`stop`); los que empiezan hoy mantienen metadatos completos aunque acaben mañana. Las guías `guides/guide-*.xml` no se modifican y siguen publicándose en XML.
13. Cada generador conserva su última guía válida si una ejecución falla. La fusión global reutiliza esas guías; no se usan artifacts de Actions.
14. Las guías públicas están en `https://raw.githubusercontent.com/hectorzin/epg/main/guides/guide.xml.gz` y en cada `guides/guide-*.xml` nacional, incluidas `guides/guide-be.xml`, `guides/guide-ca.xml` y `guides/guide-af.xml`. La global es GZIP; las nacionales siguen en XML.
15. Puedes lanzar manualmente cada generador nacional sin ejecutar el orquestador; el global solo se actualiza con el orquestador o si vuelves a fusionar en local y publicas.

**Nueva región:** la guía se guarda en `guides/guide-XX.xml`. Debe incluir su propio par de ficheros `epg/aliases-XX.json` y `epg/xtream-aliases-XX.json`, un paso `process-epg.py --profile …` en el workflow y validación de que cada clone Xtream existe en el XMLTV publicado. Si puede compartir ids con otra guía, hay que añadir `guides/guide-XX.xml` a las listas de guías ocupadas (Bélgica lee Francia, Países Bajos y el resto de nacionales desde `guides/`; Canadá lee todas las nacionales ya publicadas; África lee todas las nacionales ya publicadas). Los mappings se generan en local con `scripts/build_xtream_mappings.py` (lee la base IPTVnator en solo lectura; no se commitea ni se pasa a CI).

## Estructura del proyecto

```
epg/
├── .claude/                    # Skills, comandos y permisos para Claude Code / OpenCode
├── .opencode/commands/         # Comandos /slash de OpenCode
├── AGENTS.md                   # Instrucciones para agentes IA (Claude Code y OpenCode)
├── opencode.json               # Permisos de OpenCode
├── .github/workflows/
│   ├── epg-orchestrator.yml    # Orquestador diario (generadores + fusión)
│   ├── generate-es.yml         # Generador España
│   ├── generate-fr.yml         # Generador Francia
│   ├── generate-arabic.yml     # Generador Arabic
│   └── generate-gb.yml         # Generador Reino Unido
├── epg/
│   ├── aliases.json            # display-name Xtream (ES)
│   ├── xtream-aliases.json     # clones EPG ID Xtream (ES)
│   ├── aliases-fr.json / xtream-aliases-fr.json
│   ├── aliases-arabic.json / xtream-aliases-arabic.json
│   ├── aliases-gb.json / xtream-aliases-gb.json / xtream-pending-gb.json
│   └── xtream-pending-es.json  # asociaciones ES pendientes de fuente EPG
├── frontend/
│   ├── src/
│   │   ├── components/         # Layout, Sidebar, MobileNav, Footer, ChannelGrid
│   │   ├── data/               # Mapping canales → fuentes
│   │   ├── hooks/              # useEpgData, useLineup, useAutoRefresh, useStoredSet
│   │   ├── pages/              # Dashboard, Guide, Channels, About
│   │   └── utils/              # Parser XMLTV (DOMParser)
│   ├── dist/                   # Build de produccion (commiteado)
│   ├── package.json
│   └── vite.config.ts          # Vite + React + Tailwind CSS
├── scripts/
│   ├── commands/
│   │   ├── epg/grab.ts         # Comando principal: descarga la EPG
│   │   ├── channels/lint.mts   # Validacion de sintaxis XML
│   │   ├── channels/validate.ts # Validacion de datos de canales
│   │   ├── lineup/             # Genera lineup.json a partir de la lista M3U
│   │   └── api/load.ts         # Descarga base de datos de canales
│   ├── core/                   # Logica del grabber (queue, jobs, parsers...)
│   ├── models/                 # Modelos de datos (Channel, Guide, Feed...)
│   ├── types/                  # Definiciones de tipos TypeScript
│   ├── process-epg.py          # Capa Xtream (alias + clones)
│   ├── build_xtream_mappings.py
│   ├── xtream_matching.py
│   ├── compare_xtream_layer.py
│   └── constants.ts            # Rutas y constantes globales
├── sites/
│   ├── movistarplus.es/        # Parser + canales de Movistar+
│   ├── orangetv.orange.es/     # Parser + canales de Orange TV
│   └── programacion-tv.elpais.com/ # Parser + canales de El Pais
├── tests/                      # Tests (Jest)
├── guides/                     # Guías publicadas. Las futuras guías nacionales van aquí
│   ├── guide-*.xml             # Guías nacionales en XML
│   └── guide.xml.gz            # Guía global publicada por GitHub Actions (GZIP; ignorada en local)
├── guide.xml                   # XMLTV local sin comprimir (ignorado; el orquestador no lo publica)
├── lineup.json                 # Salida generada (grupos de la Guia TV) - en .gitignore
├── netlify.toml                # Config de despliegue
├── package.json
└── tsconfig.json
```

### Anatomia de un site

Cada directorio dentro de `sites/` contiene:

```
sites/ejemplo.com/
├── ejemplo.com.config.js       # Configuracion del parser (URL, parser HTML/JSON, timezone)
├── ejemplo.com.channels.xml    # Lista de canales en formato XML
├── ejemplo.com.test.js         # Tests del parser
├── __data__/                   # Fixtures para tests
└── readme.md                   # Documentacion del site
```

## Instalacion

Requisitos: [Node.js](https://nodejs.org/) (v22+) y [Git](https://git-scm.com/).

```sh
git clone https://github.com/hectorzin/epg.git
cd epg
npm install
```

## Uso

### Descargar la guia completa

Ejecuta el grab usando el fichero de canales de Movistar (que incluye canales de las 3 fuentes):

```sh
npm run grab -- --channels=sites/movistarplus.es/movistarplus.es.channels.xml --maxConnections=3 --days=2 --timeout=10000
```

Esto genera el fichero `guide.xml` en el directorio raiz.

### Capa Xtream (por región)

Tras el grab, cada generador nacional ejecuta `scripts/process-epg.py` con un perfil (`es`, `fr`,
`arabic`, `gb`, `pt`, `nl`, `it`, `de`, `tr`, `be`, `ca`, `af`). El script no vuelve a descargar parrillas: solo enriquece el XMLTV ya generado.

| Perfil | Guía de entrada | `display-name` | Clones Xtream |
| --- | --- | --- | --- |
| `es` | `guides/guide-es.xml` | `epg/aliases.json` | `epg/xtream-aliases.json` |
| `fr` | `guides/guide-fr.xml` | `epg/aliases-fr.json` | `epg/xtream-aliases-fr.json` |
| `arabic` | `guides/guide-arabic.xml` | `epg/aliases-arabic.json` | `epg/xtream-aliases-arabic.json` |
| `gb` | `guides/guide-gb.xml` | `epg/aliases-gb.json` | `epg/xtream-aliases-gb.json` |
| `be` | `guides/guide-be.xml` | `epg/aliases-be.json` | `epg/xtream-aliases-be.json` |
| `ca` | `guides/guide-ca.xml` | `epg/aliases-ca.json` | `epg/xtream-aliases-ca.json` |
| `af` | `guides/guide-af.xml` | `epg/aliases-af.json` | `epg/xtream-aliases-af.json` |

Los alias añaden los nombres exactos de la lista Xtream como `display-name`. Los clones duplican
canal y programas bajo el `epg_channel_id` de Xtream cuando la asociación es fiable; no se usa
`stream_id` como ID EPG salvo el caso conservador documentado en Arabia.

Regenerar asociaciones desde IPTVnator (solo local, variable `XTREAM_DB` opcional):

```sh
python scripts/build_xtream_mappings.py
```

Comparativa antes/después del matching:

```sh
python scripts/compare_xtream_layer.py es --output temp/guide-es-enriched.xml
python scripts/compare_xtream_layer.py fr --output temp/guide-fr-enriched.xml
python scripts/compare_xtream_layer.py arabic --output temp/guide-arabic-enriched.xml
python scripts/compare_xtream_layer.py gb --output temp/guide-gb-enriched.xml
```

Cada región persiste pendientes en `epg/xtream-pending-{es,fr,arabic,gb}.json`, con `status`:

| status | Significado |
| --- | --- |
| `unresolved_matching_with_programming` | Hay guía con parrilla, pero el título/ID del panel no enlaza de forma fiable |
| `channel_exists_no_programming` | El canal está en el XMLTV, sin programas |
| `channel_not_in_sources` | No está en nuestras fuentes EPG |
| `ambiguous_association` | Varias guías posibles (p. ej. regional o homónimos) |

Regenerar mappings y pendientes: `python scripts/build_xtream_mappings.py`. Comparar cobertura
real del catálogo Xtream (sin contar clones como canales originales): `python scripts/compare_xtream_catalog.py fr`.

### Normalizar y completar una guia local (España, optativo)

Para pruebas locales sobre la guía española:

```sh
python scripts/process-epg.py --input guides/guide-es.xml --output temp/guide.final.xml --profile es
```

El catálogo Xtream opcional (`--xtream-catalog`) debe ser JSON con `xtream_id`, `name`, `epg_id` y
`category`; no se distribuye en este repositorio.

El descubrimiento web de canales Movistar es optativo y se activa con `--discover-channels`.
Los canales nuevos usan el ID XMLTV estable `MovistarPlus.<site_id>` (por ejemplo,
`MovistarPlus.mbalct`); los IDs y metadatos de los canales definidos en XML se conservan.
Para canales descubiertos se descartan los bloques genéricos con el nombre del canal, mientras
que los programas concretos de parrillas mixtas se mantienen.

```sh
npm run grab -- --channels=sites/movistarplus.es/movistarplus.es.channels.xml --discover-channels --output=guide-discovery.xml
```

### Publicar XMLTV con GitHub Actions

| Workflow | Uso |
| --- | --- |
| `epg-orchestrator.yml` | Cron diario 03:00 UTC. Ejecuta generadores en paralelo y fusiona al final. |
| `generate-es.yml` | Solo `guides/guide-es.xml`. Manual o invocado por el orquestador. |
| `generate-fr.yml` | Solo `guides/guide-fr.xml`. Manual o invocado por el orquestador. |
| `generate-arabic.yml` | Solo `guides/guide-arabic.xml`. Manual o invocado por el orquestador. |
| `generate-gb.yml` | Solo `guides/guide-gb.xml` (upstream iptv-org/epg: EPGShare UK1, Sky, tv24, Virgin). |

El fusionador descubre automáticamente los ficheros `guides/guide-XX.xml` (incluido `guide-ar.xml` para
Argentina) y el nombre especial `guide-arabic.xml`; este último no se confunde con Argentina.
`scripts/ci/publish-xmltv.sh` hace commit y push con reintentos tras `git pull`, evitando conflictos
cuando los generadores publican a la vez. La URL pública de la guía global es
`guides/guide.xml.gz` en la rama `main`. Las guías nacionales siguen en XML dentro de `guides/`. La parrilla global
sigue limitada a hoy y mañana en `Europe/Madrid`.

### Descargar solo un site concreto

```sh
npm run grab -- --site=orangetv.orange.es
```

### Dashboard (desarrollo)

```sh
cd frontend
npm install
npm run dev
```

El servidor de desarrollo arranca en `http://localhost:5173` y carga `guide.xml` y `lineup.json` desde la raiz del proyecto. Si no hay `lineup.json`, la parrilla muestra todos los canales en orden alfabetico.

Para compilar el dashboard para produccion:

```sh
cd frontend
npm run build
```

> El plugin de Vite copia automaticamente el `guide.xml` local (sin comprimir) y `lineup.json` de la raiz al directorio `dist/` durante el build. La guia publicada es `guides/guide.xml.gz`; Netlify redirige `/guide.xml` y `/guide.xml.gz` a ese fichero.

### Lineup de la Guia TV

La parrilla de la Guia TV agrupa y ordena los canales igual que una lista M3U privada. El comando `lineup:generate` descarga la lista, se queda con los canales cuyo `tvg-id` existe en `guide.xml` y escribe `lineup.json`:

```sh
M3U_URL='<url de la lista>' npm run lineup:generate
```

| Opcion | Descripcion | Default |
| --- | --- | --- |
| `-g, --guide <ruta>` | Guia XMLTV con la que cruzar los canales | `guide.xml` |
| `-o, --output <ruta>` | Fichero de salida | `lineup.json` |

`lineup.json` solo contiene los nombres de grupo (sin prefijos como `[ES]` o `EU | SPAIN`), los IDs de canal de la EPG en el orden de la lista y el logo de cada canal. La URL de la lista, las URLs de stream y los nombres de la M3U nunca se escriben en disco, en los logs ni en la web.

### Opciones del grab

```
Opciones:
  -s, --site <nombre>             Nombre del site a usar
  -c, --channels <ruta>           Ruta al fichero .channels.xml
  -o, --output <ruta>             Fichero de salida (default: "guide.xml")
  -l, --lang <codigos>            Filtrar por idioma (ej: "es,en")
  -t, --timeout <ms>              Timeout por peticion en ms (default: 0)
  -d, --delay <ms>                Retardo entre peticiones en ms (default: 0)
  --days <dias>                   Numero de dias a descargar
  --maxConnections <numero>       Peticiones simultaneas (default: 1)
  --gzip                          Generar version comprimida .xml.gz
```

## GitHub Action

El orquestador `.github/workflows/epg-orchestrator.yml` se ejecuta:

- **Automaticamente** cada dia a las 03:00 UTC (05:00 hora de Madrid en invierno, 06:00 en verano)
- **Manualmente** desde la pestana Actions (`workflow_dispatch`)

Los generadores `generate-es.yml` y `generate-fr.yml` tambien admiten ejecucion manual aislada.
Las publicaciones usan el `GITHUB_TOKEN` del workflow con permiso `contents: write`; no hace falta PAT
para las guias XMLTV. El paso de lineup (`M3U_URL`) sigue siendo independiente del orquestador nacional.

## Tests

```sh
npm test
```

Ejecuta los tests de los parsers de cada site y los tests de los comandos, incluido el generador del lineup.

## Lint

```sh
npm run lint
```

## Fusión global manual

```sh
python scripts/merge-national-guides.py --root . --output guide.xml
python scripts/xmltv_gzip.py validate guide.xml
python scripts/xmltv_gzip.py pack guide.xml guides/guide.xml.gz
```

El orquestador no deja el XML global en el repositorio: lo escribe en un temporal, lo valida y
publica solo `guides/guide.xml.gz`. El comando anterior sirve para inspeccionar la fusión en local.
`--root .` lee las guías nacionales desde `guides/`.
Usa el mismo recorte de dos días en `Europe/Madrid`. Opcionalmente puedes fijar el día de
referencia con `--reference-date YYYY-MM-DD` (zona Madrid) para pruebas o reproducción.

## Uso de la guía global

`guides/guide.xml.gz` combina las guías nacionales y limita la parrilla a **hoy y mañana** (calendario de Madrid). Los ficheros `guides/guide-*.xml` conservan su ventana completa y el formato XML. El contenido descomprimido es [XMLTV](https://wiki.xmltv.org/index.php/XMLTVFormat) y es compatible con:

- **Kodi** (PVR IPTV Simple Client)
- **TiviMate**
- **Plex** (con plugin XMLTV)
- **VLC**
- Cualquier reproductor IPTV que soporte guias EPG en formato XMLTV

### URL de la guia

La guia es publica y gratuita:

```
https://raw.githubusercontent.com/hectorzin/epg/main/guides/guide.xml.gz
https://raw.githubusercontent.com/hectorzin/epg/main/guides/guide-es.xml
https://raw.githubusercontent.com/hectorzin/epg/main/guides/guide-fr.xml
https://raw.githubusercontent.com/hectorzin/epg/main/guides/guide-arabic.xml
```

## Origen

Fork de [iptv-org/epg](https://github.com/iptv-org/epg), simplificado para mantener fuentes de TV en España y publicar también una guía nacional árabe.

Creado por [raulfdeztdo](https://github.com/raulfdeztdo).

## Licencia

[CC0](LICENSE)

## Agentes IA (Claude Code y OpenCode)

El repositorio esta preparado para trabajar con [Claude Code](https://claude.com/claude-code) y [OpenCode](https://opencode.ai) con la misma configuracion:

| Pieza | Claude Code | OpenCode |
| --- | --- | --- |
| Instrucciones | `AGENTS.md` | `AGENTS.md` |
| Skills | `.claude/skills/` | `.claude/skills/` |
| Comandos | `.claude/commands/` | `.opencode/commands/` |
| Permisos | `.claude/settings.json` | `opencode.json` |

Comandos disponibles en ambas herramientas: `/verificar`, `/grab-site <site>`, `/nuevo-canal <canal>` y `/nuevo-site <dominio>`. Las reglas de mantenimiento estan en `AGENTS.md`.
