# EPG - Guia de Programacion TV Espana y arabe

Fork simplificado de [iptv-org/epg](https://github.com/iptv-org/epg) para descargar la EPG de canales de TV en Espana y generar una guia nacional arabe.

## Comandos

```bash
npm run grab -- --channels=sites/movistarplus.es/movistarplus.es.channels.xml --maxConnections=3 --days=2 --timeout=10000  # Descarga EPG completa
npm run grab -- --site=orangetv.orange.es           # Descarga solo un site
npm test                                             # Ejecuta tests (Jest + SWC)
npm run lint                                         # ESLint
npm run channels:lint -- <fichero.channels.xml>      # Validar sintaxis XML de canales
npm run channels:validate -- <fichero.channels.xml>  # Validar datos de canales
M3U_URL=<url> npm run lineup:generate                # Genera lineup.json (grupos/orden de la Guia TV)
```

- Ejecuta siempre `npm test` despues de modificar parsers o tests.
- El test runner usa `cross-env TZ=Pacific/Nauru` para forzar una zona horaria no estandar y detectar bugs de timezone.

## Estructura del proyecto

```
epg/
├── .claude/
│   ├── skills/                 # Skills compartidas (Claude Code + OpenCode)
│   ├── commands/               # Comandos /slash de Claude Code
│   └── settings.json           # Permisos compartidos de Claude Code
├── .opencode/commands/         # Comandos /slash de OpenCode (copia de .claude/commands)
├── .github/workflows/
│   ├── epg-orchestrator.yml    # Orquestador diario (generadores + fusión global)
│   ├── generate-es.yml         # Publica solo guides/guide-es.xml
│   ├── generate-fr.yml         # Publica solo guides/guide-fr.xml
│   ├── generate-arabic.yml     # Publica solo guides/guide-arabic.xml
│   ├── generate-gb.yml         # Publica solo guides/guide-gb.xml
│   ├── generate-pt.yml         # Publica solo guides/guide-pt.xml
│   ├── generate-nl.yml         # Publica solo guides/guide-nl.xml
│   ├── generate-it.yml         # Publica solo guides/guide-it.xml
│   ├── generate-de.yml         # Publica solo guides/guide-de.xml
│   ├── generate-tr.yml         # Publica solo guides/guide-tr.xml
│   ├── generate-be.yml         # Publica solo guides/guide-be.xml
│   ├── generate-ca.yml         # Publica solo guides/guide-ca.xml
│   └── generate-af.yml         # Publica solo guides/guide-af.xml
├── scripts/
│   ├── arabic-epg.py           # Selección de cobertura y fusión de XMLTV árabe
│   ├── ca-epg.py               # Selección y fusión de la guía canadiense
│   ├── af-epg.py               # Selección y fusión de la guía africana
│   ├── grab_epgshare.py        # Extra EPGShare (Rally.TV.de) para ES y DE
│   ├── commands/
│   │   ├── epg/grab.ts         # Punto de entrada principal
│   │   ├── channels/lint.mts   # Linter XML
│   │   ├── channels/validate.ts
│   │   ├── lineup/generate.ts  # Genera lineup.json a partir de la lista M3U privada
│   │   └── api/load.ts         # Descarga DB de canales (postinstall)
│   ├── core/                   # Motor del grabber (queue, jobs, config loader...)
│   ├── models/                 # Modelos (Channel, Guide, Feed, ChannelList...)
│   ├── types/                  # Tipos TypeScript (.d.ts)
│   └── constants.ts            # Rutas globales (SITES_DIR, DATA_DIR, etc.)
├── sites/
│   ├── movistarplus.es/        # Scraping HTML (cheerio) - 160 canales
│   ├── orangetv.orange.es/     # API JSON (3 segmentos de 8h) - usa @ntlab/sfetch
│   └── programacion-tv.elpais.com/ # API JSON (schedule + program details)
├── frontend/                   # Dashboard React + Vite + Tailwind (package.json propio)
│   ├── src/components/ChannelGrid.tsx # Parrilla agrupada de la Guia TV
│   ├── src/hooks/              # useEpgData, useLineup, useAutoRefresh, useStoredSet
│   ├── vite.config.ts          # Sirve/copia guide.xml local y lineup.json desde la raiz
│   └── dist/                   # Build de produccion commiteado (lo publica Netlify)
├── tests/                      # Tests de comandos (Jest)
├── guides/                     # Guias publicadas; las futuras nacionales van aqui
│   ├── guide-*.xml             # Guias nacionales en XML
│   └── guide.xml.gz            # Guia global publicada (GZIP) - en .gitignore; CI la fuerza
├── guide.xml                   # XMLTV global local, sin comprimir - en .gitignore
├── lineup.json                 # Salida generada (grupos y orden de canales) - en .gitignore
├── AGENTS.md                   # Instrucciones para agentes (fuente unica)
├── opencode.json               # Configuracion de OpenCode (permisos)
├── netlify/edge-functions/     # Bloqueo de clientes abusivos de /guide.xml y /guide.xml.gz
├── netlify.toml                # Publica frontend/dist sin build y redirige la guia a GitHub
├── package.json
└── tsconfig.json
```

## Fuentes de datos (sites/)

Cada site tiene esta estructura:
```
sites/<dominio>/
├── <dominio>.config.js       # Parser: exports { site, days, url(), parser(), channels() }
├── <dominio>.channels.xml    # Lista de canales XML
├── <dominio>.test.js         # Tests con fixtures en __data__/
├── __data__/                 # HTML/JSON fixtures para tests
└── readme.md
```

### Particularidades importantes

- **movistarplus.es.channels.xml es el fichero maestro**: contiene canales de las 3 fuentes. Cada `<channel>` tiene un atributo `site` que indica de que fuente obtener datos. El workflow solo ejecuta grab contra este fichero.
- **movistarplus.es** hace scraping HTML: extrae programas de `div[id^="ele-"]`, obtiene descripciones haciendo peticiones individuales a cada programa. Detecta cruce de medianoche comparando horas consecutivas.
- **orangetv.orange.es** descarga 3 segmentos JSON de 8 horas cada uno para cubrir las 24h del dia.
- **programacion-tv.elpais.com** hace 2 llamadas: una para la parrilla diaria y otra para detalles de cada programa.

## Convenciones de codigo

- TypeScript strict mode. Modulos CommonJS.
- Sin punto y coma (Prettier: `semi: false`).
- Comillas simples (`singleQuote: true`).
- Ancho maximo 100 caracteres.
- Los configs de sites son `.js` (no TypeScript) porque se cargan dinamicamente en runtime.
- Los tests de sites usan `jest.mock('axios')` para evitar peticiones reales.

## GitHub Actions (EPG)

- `epg-orchestrator.yml`: cron 03:00 UTC y `workflow_dispatch`. Llama en paralelo a
 `generate-es.yml`, `generate-fr.yml`, `generate-arabic.yml`, `generate-gb.yml`,
 `generate-pt.yml`, `generate-nl.yml`, `generate-it.yml`, `generate-de.yml`,
 `generate-tr.yml`, `generate-be.yml`, `generate-ca.yml` y `generate-af.yml`, luego fusiona con
  `scripts/merge-national-guides.py` (`--root .`, que lee `guides/`). El XML global se escribe en un fichero
  temporal, se valida igual que antes y se comprime con GZIP nivel 9 y `mtime=0`
  (`scripts/xmltv_gzip.py`). Solo se publica si el contenido descomprimido es idéntico a ese
  XML. El repositorio central recibe únicamente `guides/guide.xml.gz`; el `guide.xml` global sin
  comprimir se elimina del índice. Las guías nacionales siguen en XML dentro de `guides/`. La fusión global no
  altera los `guides/guide-*.xml`: conserva todos los canales (IDs, alias, logos), pero filtra la parrilla
  a hoy y mañana en `Europe/Madrid` (XMLTV con offset; programas que solapan el intervalo se
  mantienen). No ampliar esa ventana. Solo en la guía global, los programas cuya hora de inicio
  cae en **mañana** (Madrid) conservan `title`, `category` y los atributos del `<programme>`; el
  resto de metadatos del programa se omiten. Los que empiezan hoy, aunque terminen mañana,
  conservan todos los metadatos. Las validaciones que comparan con la versión anterior leen
  `guides/guide.xml.gz` descomprimiendo el GZIP.
- El generador turco publica `guides/guide-tr.xml` con `scripts/tr-epg.py` (Digiturk → D-Smart →
 TV+ → Türksat Kablo → EPGShare TR1). Si el grabber de iptv-org no trae programas de
 D-Smart, TV+ o Türksat, `scripts/grab_tr_public.py` usa su API pública. Türksat verifica TLS;
 si el servidor no envía el intermedio, se completa con el certificado GlobalSign indicado en
 el propio certificado y se vuelve a comprobar el nombre. Los ids publicados
 quedan en `.tr`; si otro país ya usa el mismo id se reescribe a `@Turkey`. Una estación ya
 publicada conserva su id aunque otra fuente la escriba con otras mayúsculas o con otro xmltv id.
 Si sigue en un catálogo de origen pero el grab no trae programas, se reemite el canal (id,
 display-name e icono) sin recuperar la parrilla anterior. Tivibu no se
 usa: su parrilla pide un token de abonado. Tras el merge crudo, `process-epg --profile tr`
 con `epg/aliases-tr.json` y `epg/xtream-aliases-tr.json`. El grab usa `--days=2` y la zona
 `Europe/Istanbul` (UTC+3).
- El generador belga publica `guides/guide-be.xml` con `scripts/be-epg.py` (Telenet →
 mon-programme-tv.be → vtm.be, y para BX1, Canal Zoom, Télé Sambre y TV Lux también
 POST Luxembourg → Télé Câble Sat) y la tabla curada `epg/be-stations.json`. Solo entran
 los canales de `[BL] BELGIUM`. Lee las guías ya publicadas en `guides/`, sobre todo
 `guides/guide-fr.xml` y `guides/guide-nl.xml`. Si el mismo id ya tiene programas en otra guía nacional, no se
 vuelve a descargar: se conserva ese id, se añade el nombre Xtream y los programas siguen
 en la guía que ya los tenía. El `epg_channel_id` distinto se publica como canal propio con
 esa parrilla copiada, sin repetirla sobre el id compartido. No se usa pickx.be (roto), ni
 el feed francés de Eleven/Nat Geo, ni RTV Oost neerlandesa para TV Oost. Tras el merge
 crudo, `process-epg --profile be` con `epg/aliases-be.json` y `epg/xtream-aliases-be.json`
 (vacío: los ids Xtream ya van en la guía). El grab usa `--days=2`.
- El generador canadiense publica `guides/guide-ca.xml` con `scripts/ca-epg.py` (TV Hebdo →
  EPGShare CA2 → open-epg) y la tabla curada `epg/ca-stations.json`. Solo entran los canales de
  `[CA] CANADA`. Lee las guías nacionales ya publicadas en `guides/`. Si un id ya tiene programas,
  no vuelve a descargar esa parrilla: `LoveNature.ca@SD` sigue en `guides/guide-nl.xml`. Los feeds
  regionales, deportivos y de distinta franja (CBC/CTV/Global por ciudad, TSN 1–5, Sportsnet
  East/Ontario/Pacific/West, Crave y HBO este frente a oeste) no se mezclan. Los sucesores
  canadienses verificados usan la parrilla actual: Animal Planet es CTV Wild, Discovery Science es
  CTV Nature, Discovery Velocity es CTV Speed, DIY Network es Magnolia Network, Moi et Cie es
  Témoin y Ztélé es Z. Global News Vancouver usa solo Global News BC1. BBC World News coincide
  en todas las horas solapadas con BBC News North America y se publica en ese mismo id.
  Nickelodeon, Disney Junior, Disney XD y ABC Spark cerraron en 2025 y
  no heredan otra señal. No se usa la parrilla
  estadounidense de Zap2it ni un ABC/CBS genérico. TV Hebdo solo aporta canales franceses; EPGShare
  CA2 conserva el corte regional en inglés y francés. Tras el merge crudo, `process-epg --profile ca`
  con `epg/aliases-ca.json` y `epg/xtream-aliases-ca.json` (vacío: los ids Xtream ya van en la guía).
  El grab usa `--days=2`.
- El generador africano publica `guides/guide-af.xml` con `scripts/af-epg.py` (Canal+ Afrique →
  TMA Caraïbes) y la tabla curada `epg/af-stations.json`. Solo entran los canales de `[AF] AFRIQUE`.
  Lee las guías nacionales ya publicadas, sobre todo `guides/guide-fr.xml`, `guides/guide-pt.xml`,
  `guides/guide-gb.xml` y `guides/guide-arabic.xml`. Si un id ya tiene programas, no vuelve a
  descargar esa parrilla: `RTI1.ci@SD`, `CRTV.cm@SD`, `ORTM1.ml@SD`, `2STV.sn@SD` y el resto de
  señales ya publicadas siguen en la guía que las tenía. TVC News Nigeria reutiliza
  `TVCNews.ng@SD` de la guía británica y no copia sus programas. No se mezclan variantes: RTS Senegal no
  usa RTS Suiza, ORTM 2 no usa ORTM 1, Canal 2 Internacional no usa Canal 2 Movies, Al Jazeera
  árabe no usa Al Jazeera English, TV5MONDE Info no usa TV5MONDE Afrique y TVM1 no usa TVM
  Internacional. Los `epg_channel_id` del panel están vacíos, así que no hay clones. Tras el
  merge crudo, `process-epg --profile af` con `epg/aliases-af.json` y `epg/xtream-aliases-af.json`
  (vacío). El grab usa `--days=2`.
- El generador alemán publica `guides/guide-de.xml` con `scripts/de-epg.py` (Magenta → Magenta web →
  TV Heute, más extras EPGShare). Rally.TV (`Rally.TV.de`, site_id `RALLY_TV1#Rally.TV.de`) se
  descarga con `scripts/grab_epgshare.py` (mismo contrato URL que iptv-org `epgshare01.online`).
  El ID se comparte con `guides/guide-es.xml`; no se reescribe por colisión internacional. La fusión
  global conserva un solo canal y no duplica programas. Si un canal publicado sigue
  en el catálogo de origen pero el grab no trae programas, se reemite el `<channel>`
  (ID, display-name, icono) sin recuperar parrilla caducada. Magenta «Sky Sport
  Bundesliga 10» (`389264936256`) usa `SkySportBundesliga11.de@SD` para no chocar
  con el 10 ya publicado (Magenta 9). Tras el merge crudo,
  `process-epg --profile de` con `epg/aliases-de.json`. El grab usa `--days=2`.
- El generador español también descarga Rally.TV con `scripts/grab_epgshare.py` y lo fusiona
  vía `merge-guides.py --epgshare`. Display-name Xtream exacto `DAZN RALLY TV` en
  `epg/aliases.json` y `epg/aliases-de.json`; sin clones en `xtream-aliases*.json`. No usar Pluto TV.
- El generador portugués publica `guides/guide-pt.xml` con `scripts/pt-epg.py` (prioridad NOS → MEO →
 Vodafone → TVI, identidad de mercado PT, colisiones con feed `Portugal`). Tras el merge crudo,
 `process-epg --profile pt` con `epg/aliases-pt.json` y `epg/xtream-aliases-pt.json`. El grab usa
 `--days=2`.
- El generador neerlandés publica `guides/guide-nl.xml` con `scripts/nl-epg.py` (Ziggo → Delta →
  tvgids.nl, huecos por hora de inicio, colisiones con feed `@Netherlands`). Al seleccionar canales
  lee `guides/guide-es.xml`, `guides/guide-fr.xml`, `guides/guide-arabic.xml`, `guides/guide-gb.xml`
  y `guides/guide-pt.xml`. Bélgica, a su vez, lee `guides/guide-nl.xml`. Delta usa selección
  incremental y `epg/nl-delta-grab-excludes.json` para omitir `PROGRAM_NOT_FOUND` conocidos. Tras
  el merge crudo, `process-epg --profile nl` con `epg/aliases-nl.json` y
  `epg/xtream-aliases-nl.json` (sin clones automáticos; equivalencias curadas en
  `epg/global-xtream-policy.json`). Validación con `scripts/nl_publish_validate.py` y simulación
  AquaPlay/IPTVnator vía `scripts/nl_catalog_match.py` cuando existe
  `temp/nl-xtream-catalog.json`. El panel NH Nieuws debe resolver a `NH.nl@SD`, no clonar
  `nponieuws.nl`. El grab usa `--days=2`.
- El generador italiano publica `guides/guide-it.xml` con `scripts/it-epg.py` (guidatv.sky.it →
  mediasetinfinity → raiplay.it → tivu.tv, selección incremental, colisiones internacionales
  `@Italy`). No usa guida.tv, superguidatv ni EPGShare. Tras el merge crudo,
  `process-epg --profile it` con `epg/aliases-it.json` y `epg/xtream-aliases-it.json` (vacío:
  panel Xtream sin `epg_channel_id`). Validación con `scripts/it_publish_validate.py` y cobertura
  curada vía `scripts/it_catalog_match.py`. El grab usa `--days=2`.
- El generador British publica `guides/guide-gb.xml` con `scripts/gb-epg.py` (selección incremental,
  merge por calidad Virgin → Sky → tv24 → EPGShare, IDs débiles rechazados, colisiones @UK frente a
  ES/FR/Arabic). Fuentes en upstream iptv-org/epg: EPGShare UK1, Sky (site_id `GB#`), tv24.co.uk y
  Virgin TV Go. Tras el merge crudo, `process-epg --profile gb` con `epg/aliases-gb.json` y
  `epg/xtream-aliases-gb.json`; los mappings curados viven en `scripts/apply_gb_xtream_curated.py`.
- El generador Arabic publica `guides/guide-arabic.xml` con Shahid primero y elCinema, OSN, beIN,
  beIN SPORTS MENA, Al Jazeera, ART y Ayn como fuentes complementarias. Después añade Laâyoune
  y Tamazight desde la parrilla pública de SNRT (`scripts/grab_snrt.py`, `epg/snrt-ma.channels.xml`);
  el grabber de iptv-org recibe 403 en esa web. No copia un id que ya tenga programas en otra guía
  nacional. Mantiene dos días, limita elCinema a una conexión con un segundo de demora, conserva
  títulos árabes y omite SAT.tv y EPGShare01 mientras no aporten programación válida. Marruecos,
  Argelia y Túnez no tienen guía propia: sus canales del panel reutilizan los ids ya publicados.
- Cada generador nacional publica únicamente su guía vía `scripts/ci/publish-xmltv.sh`
  (reintentos con `git fetch`/`checkout` para evitar conflictos de push concurrentes).
- **Capa Xtream obligatoria:** tras el grab/XMLTV crudo, cada workflow ejecuta
  `scripts/process-epg.py` con `--profile es|fr|arabic|gb|pt|nl|it|de|tr|be|ca|af` y los JSON en `epg/aliases*.json` /
  `epg/xtream-aliases*.json` (p. ej. `aliases-gb.json`, `xtream-aliases-gb.json`). El paso de
  publish valida que cada clone exista en la guía. Los mappings se regeneran en local con
  `python scripts/build_xtream_mappings.py` (`XTREAM_DB` opcional); no commitear credenciales,
  URLs ni la base IPTVnator.
- Si un país falla, no se sobrescribe su guía; el fusionador usa las copias ya en `main`.
- Añadir una guía nacional: publicar `guides/guide-XX.xml` (código ISO de dos letras); el fusionador la
  detecta dentro de `guides/`. La guía árabe usa el nombre especial `guide-arabic.xml` para no colisionar con
  `guide-ar.xml` de Argentina. Toda región nueva requiere alias + xtream-aliases + paso
  `process-epg` en su workflow. Si comparte ids con otra guía, añadir el fichero a las listas de
  guías ocupadas: Bélgica lee `guides/guide-fr.xml`, `guides/guide-nl.xml` y el resto de nacionales;
  Canadá lee todas las nacionales ya publicadas, incluida `guides/guide-nl.xml` y `guides/guide-af.xml`;
  África lee todas las nacionales ya publicadas;
  Países Bajos lee `guides/guide-fr.xml` entre otras, y Francia publica la suya para que ambos la usen.
- next-blog no forma parte de esta publicación. El orquestador no llama a `hectorzin/next-blog`
  ni usa un secreto para avisarle. Su importador descarga
  `https://raw.githubusercontent.com/hectorzin/epg/main/guides/guide.xml.gz` y, mientras dura
  la transición, acepta la ruta anterior `guide.xml.gz` y el XML plano `guide.xml` si la nueva
  responde 404. Las URLs públicas de Vercel y Byet no cambian.
- Runners: `ubuntu-24.04` (ES + merge) y `ubuntu-latest` (FR). `GITHUB_TOKEN` con `contents: write`.
- `actions/checkout` fijado por SHA con `persist-credentials: false`. `npm ci --ignore-scripts` +
  `npm run api:load` antes del grab español.

## Skills disponibles

El directorio `.claude/skills/` contiene guias especializadas que el agente puede cargar segun la tarea.
Claude Code y OpenCode las descubren automaticamente en esa ruta:

| Skill | Uso |
|-------|-----|
| `web-scraping-patterns` | Crear/modificar parsers de sites: cheerio, APIs JSON, dayjs/timezones, peticiones HTTP en lotes |
| `xmltv-epg` | Formato XMLTV, estructura de `channels.xml`, pipeline del grabber, anadir canales/fuentes |
| `jest-testing` | Tests de parsers: fixtures, mocking de axios, aserciones de fechas, depuracion de timezone |
| `nodejs-best-practices` | Decisiones de arquitectura Node.js, patrones async, manejo de errores |
| `typescript-advanced-types` | Tipos avanzados de TypeScript: generics, conditional types, utility types |

Carga la skill correspondiente cuando trabajes en:
- **Parsers de sites** -> `web-scraping-patterns` + `xmltv-epg`
- **Tests** -> `jest-testing`
- **Codigo TypeScript en scripts/** -> `typescript-advanced-types` + `nodejs-best-practices`

## Notas para el agente

- No modificar los ficheros en `scripts/core/` ni `scripts/models/` salvo que sea estrictamente necesario. Son del upstream de iptv-org/epg y conviene mantener compatibilidad.
- Al crear o modificar parsers de sites, siempre actualizar los tests y fixtures correspondientes.
- Los ficheros `.channels.xml` usan encoding UTF-8 y formato XML con indentacion de 4 espacios.
- Las guías nacionales viven en `guides/` y están versionadas. `guides/guide.xml.gz` está en
  `.gitignore`; el orquestador lo publica con `git add -f`. `guide.xml` en la raíz sigue siendo
  la copia local sin comprimir y también está ignorado. El orquestador genera el XML global en
  un temporal, publica `guides/guide.xml.gz` y quita de la raíz el `guide.xml` y el `guide.xml.gz`
  que aún estuvieran en el índice. No leas la guia entera: sin comprimir pesa decenas de MB. Lo mismo para
  `frontend/dist/guide.xml`.
- No hagas `npm run build` en `frontend/` ni modifiques `frontend/dist/` salvo que se pida: el
  build commiteado es lo que publica Netlify. Si cambias `frontend/src/`, el cambio no se publica
  hasta que se haga el build y se commitee `frontend/dist/`. Tras el build, comprueba que
  `frontend/dist/guide.xml` no ha retrocedido a una version antigua del `guide.xml` local.

## Guia TV y lista M3U privada

- La vista por defecto de la Guia TV es una parrilla agrupada que sigue los grupos y el orden de
  una lista M3U privada. `scripts/commands/lineup/` la descarga desde la variable de entorno
  `M3U_URL` y escribe `lineup.json` solo con nombres de grupo, IDs de canal de la EPG y logos.
- La URL de la lista y su contenido son privados: no los escribas en ficheros, logs, tests,
  commits ni en el frontend. Nunca anadas a `lineup.json` URLs de stream ni `tvg-name`.
- Si `lineup.json` no existe, la parrilla muestra todos los canales en orden alfabetico.
- Los grupos contraidos se guardan en `localStorage` (`epg.guide.collapsedGroups`). La Guia TV
  refresca `/guide.xml` y `lineup.json` cada 5 minutos mientras esta abierta. En local Vite
  sirve el `guide.xml` sin comprimir. En produccion Netlify redirige `/guide.xml` y
  `/guide.xml.gz` a `guides/guide.xml.gz` de GitHub y el cliente lo descomprime. `frontend/dist` no incluye ese cambio hasta el
  proximo build.
- El barrel file `scripts/core/index.ts` reexporta todos los modulos de core. Si se anade o elimina un modulo, actualizar el barrel.
- Lo mismo para `scripts/models/index.ts`.

## Compatibilidad Claude Code / OpenCode

El flujo de trabajo funciona igual con ambas herramientas:

| Pieza | Claude Code | OpenCode |
|-------|-------------|----------|
| Instrucciones | `AGENTS.md` (nativo desde v2.1.277) | `AGENTS.md` |
| Skills | `.claude/skills/` | `.claude/skills/` (ruta compatible) |
| Comandos | `.claude/commands/` | `.opencode/commands/` |
| Permisos | `.claude/settings.json` | `opencode.json` |

Comandos disponibles en ambas herramientas:

| Comando | Uso |
|---------|-----|
| `/verificar [fichero.channels.xml]` | Tests, lint y validacion de canales |
| `/grab-site <site>` | Descarga un dia de un site y revisa la salida |
| `/nuevo-canal <canal>` | Anade un canal al fichero maestro y lo valida |
| `/nuevo-site <dominio>` | Crea una fuente nueva con parser, tests y fixtures |

Reglas de mantenimiento:

- `AGENTS.md` es el unico fichero de instrucciones. No crees `CLAUDE.md` ni `CLAUDE.local.md`:
  si existen, Claude Code los lee en lugar de `AGENTS.md`.
- Las skills van en `.claude/skills/<nombre>/SKILL.md`. El campo `name` del frontmatter debe
  coincidir con el directorio (`^[a-z0-9]+(-[a-z0-9]+)*$`). Los campos extra van bajo
  `metadata`. No las dupliques en `.agents/skills/` ni en `.opencode/skills/`: OpenCode tambien
  lee esas rutas y tendria nombres repetidos.
- `.claude/commands/` y `.opencode/commands/` deben ser identicos. En el frontmatter usa solo
  `description`, que es el campo comun a las dos herramientas. Tras editar un comando:
  `cp .claude/commands/*.md .opencode/commands/`.
- Si cambias los permisos de `.claude/settings.json`, refleja el mismo cambio en `opencode.json`.

## Problemas conocidos

- `npm test` tiene 9 fallos previos en `tests/commands/epg/grab.test.ts`, ajenos a los parsers y
  al lineup. No los tomes como regresion de tus cambios; comprueba que el numero no aumenta.
- La guia global contiene algunos programas duplicados (mismo canal y hora de inicio). En la linea de
  tiempo de la Guia TV generan avisos de claves duplicadas de React en la consola.
- El User-Agent `OTT-TV/*` agotaba el ancho de banda del plan Free de Netlify, compartido con otros
  sitios de la cuenta. `netlify/edge-functions/block-guide-clients.ts` le responde 403 en
  `/guide.xml` y `/guide.xml.gz`. Para bloquear otro cliente, amplia el filtro `header` de su `config`.
- `netlify.toml` redirige `/guide.xml` y `/guide.xml.gz` a
  `https://raw.githubusercontent.com/hectorzin/epg/main/guides/guide.xml.gz` para no gastar el ancho de
  banda de Netlify. La URL de Netlify debe seguir funcionando porque hay listas IPTV que la usan,
  pero en el README y en la web se anuncia solo la de GitHub (`frontend/src/constants.ts`).
  `frontend/dist/guide.xml` se sigue copiando, pero la redireccion lo oculta. El `frontend/dist`
  commiteado aun anuncia y parsea el XML plano: no se regenera hasta que se pida el build.
