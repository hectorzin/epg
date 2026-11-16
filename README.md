# EPG - Guia Electronica de Programacion (TV España)

[![Netlify Status](https://api.netlify.com/api/v1/badges/ca6936cb-f26f-4be2-b332-d9e872601737/deploy-status)](https://app.netlify.com/projects/epg-spain/deploys)
[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-2088FF?logo=githubactions&logoColor=white)](https://github.com/hectorzin/epg/actions)
[![Node.js](https://img.shields.io/badge/Node.js_22-339933?logo=nodedotjs&logoColor=white)](https://nodejs.org/)
[![TypeScript](https://img.shields.io/badge/TypeScript-3178C6?logo=typescript&logoColor=white)](https://www.typescriptlang.org/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)](https://react.dev/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-38B2AC?logo=tailwindcss&logoColor=white)](https://tailwindcss.com/)
[![XMLTV](https://img.shields.io/badge/XMLTV-format-orange)](https://wiki.xmltv.org/)

Fork simplificado de [iptv-org/epg](https://github.com/iptv-org/epg) para descargar la guia de programacion (EPG) de canales de television en España.

### 🌐 [Dashboard en vivo](https://epg-spain.netlify.app/) · [guide.xml](https://raw.githubusercontent.com/hectorzin/epg/main/guide.xml)

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

> Los canales estan definidos en `sites/movistarplus.es/movistarplus.es.channels.xml`. Este fichero incluye canales de las 3 fuentes (cada canal tiene el atributo `site` indicando de donde se obtienen sus datos).

## Como funciona

1. El workflow de GitHub Actions (`update.yml`) puede ejecutarse manualmente; su cron diario permanece desactivado.
2. Lee el fichero maestro de canales y ejecuta sus parsers, con descubrimiento adicional de Movistar.
3. Procesa el XMLTV local con `scripts/process-epg.py`, que añade display aliases y clones Xtream configurados.
4. Valida el XML, la cobertura mínima y los canales requeridos, y conserva `guide.final.xml` como artefacto descargable.
5. En una ejecución manual, publica solo si `publish_to_repo` está activado. Usa `GITHUB_TOKEN` con `contents: write` limitado a ese job, y actualiza `guide.xml` en `main` solo si el SHA-256 cambia.
6. El XML público queda disponible en `https://raw.githubusercontent.com/hectorzin/epg/main/guide.xml`.

## Estructura del proyecto

```
epg/
├── .claude/                    # Skills, comandos y permisos para Claude Code / OpenCode
├── .opencode/commands/         # Comandos /slash de OpenCode
├── AGENTS.md                   # Instrucciones para agentes IA (Claude Code y OpenCode)
├── opencode.json               # Permisos de OpenCode
├── .github/workflows/
│   └── update.yml              # Workflow programado (cron diario)
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
│   └── constants.ts            # Rutas y constantes globales
├── sites/
│   ├── movistarplus.es/        # Parser + canales de Movistar+
│   ├── orangetv.orange.es/     # Parser + canales de Orange TV
│   └── programacion-tv.elpais.com/ # Parser + canales de El Pais
├── tests/                      # Tests (Jest)
├── guide.xml                   # XMLTV publicado por GitHub Actions (ignorado durante la generación local)
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

### Normalizar y completar una guia local

La segunda etapa procesa un XMLTV local generado por este repositorio y escribe una guia
definitiva en una ruta distinta. No descarga ninguna guia externa ni sobrescribe la entrada:

```sh
python scripts/process-epg.py --input guide.xml --output temp/guide.final.xml
```

`epg/aliases.json` añade los nombres alternativos como elementos `display-name`, que AquaPlay usa
para relacionar canales. `epg/xtream-aliases.json` conserva las equivalencias Xtream curadas y
duplica los canales/programas con sus IDs alternativos, manteniendo los `display-name` originales.
El catálogo Xtream, si se proporciona con `--xtream-catalog`, debe ser un JSON saneado con solo
`xtream_id`, `name`, `epg_id` y `category`; no se distribuye en este repositorio.

El descubrimiento web de canales Movistar es optativo y se activa con `--discover-channels`.
Los canales nuevos usan el ID XMLTV estable `MovistarPlus.<site_id>` (por ejemplo,
`MovistarPlus.mbalct`); los IDs y metadatos de los canales definidos en XML se conservan.
Para canales descubiertos se descartan los bloques genéricos con el nombre del canal, mientras
que los programas concretos de parrillas mixtas se mantienen.

```sh
npm run grab -- --channels=sites/movistarplus.es/movistarplus.es.channels.xml --discover-channels --output=guide-discovery.xml
```

### Publicar XMLTV con GitHub Actions

`.github/workflows/update.yml` genera la guía, aplica `scripts/process-epg.py`, valida el XMLTV,
la cobertura y los aliases configurados, y conserva `guide.final.xml` como artefacto descargable.
El job `publish` puede publicar ese mismo archivo como `guide.xml` en `main`. Como `guide.xml`
está ignorado por Git, se añade explícitamente con `git add -f`. Solo crea un commit si el
contenido cambió; verifica el SHA-256 y se detiene si `main` ya recibió otra guía o cambió el
código/configuración de generación durante el scraping.

La publicación usa el `GITHUB_TOKEN` efímero con `contents: write` limitado al job de publicación;
no requiere PAT ni otros secretos. En una ejecución manual, `publish_to_repo` está desactivado por
defecto: genera el artefacto sin publicar. Actívalo solo tras revisar la guía. El cron sigue
desactivado; al reactivarlo, las ejecuciones programadas publicarán automáticamente.

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

> El plugin de Vite copia automaticamente `guide.xml` y `lineup.json` de la raiz al directorio `dist/` durante el build. Asegurate de que el `guide.xml` local esta actualizado (`git pull`) para no publicar uno antiguo.

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

El workflow `.github/workflows/update.yml` se ejecuta:

- **Automaticamente** cada dia a las 03:00 UTC (05:00 hora de Madrid)
- **Manualmente** desde la pestana Actions del repositorio (workflow_dispatch)

Corre en un runner self-hosted (Raspberry Pi) con Node 22 del sistema y necesita estos secrets en el repositorio:

| Secret | Uso |
| --- | --- |
| `GH_TOKEN` | Personal Access Token para hacer push |
| `M3U_URL` | URL de la lista M3U con la que se genera `lineup.json` |

```sh
gh secret set M3U_URL --repo raulfdeztdo/epg
```

Si el secret no existe o la descarga falla, el workflow continua y se mantiene el `lineup.json` anterior.

## Tests

```sh
npm test
```

Ejecuta los tests de los parsers de cada site y los tests de los comandos, incluido el generador del lineup.

## Lint

```sh
npm run lint
```

## Uso del guide.xml

El fichero `guide.xml` generado esta en formato [XMLTV](https://wiki.xmltv.org/index.php/XMLTVFormat) y es compatible con:

- **Kodi** (PVR IPTV Simple Client)
- **TiviMate**
- **Plex** (con plugin XMLTV)
- **VLC**
- Cualquier reproductor IPTV que soporte guias EPG en formato XMLTV

### URL de la guia

La guia es publica y gratuita:

```
https://raw.githubusercontent.com/hectorzin/epg/main/guide.xml
```

## Origen

Fork de [iptv-org/epg](https://github.com/iptv-org/epg), simplificado para mantener unicamente las fuentes de TV en España.

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
