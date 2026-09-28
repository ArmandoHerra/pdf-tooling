// The Spanish side of every DATA file on the page.
//
// Three of the page's sections do not carry their prose in a component at
// all -- the verb roster (`verbs.ts`), the six-layer spine (`spine.json`)
// and the two contracts plus the atomic-write sequence
// (`contracts.json`). Those files are test-pinned against the product's
// own source (`tests/test_website_diagrams.py` walks `spine.json` against
// `tests/test_import_boundaries.py`'s AST walk and `ports/__init__.py`'s
// PORTS tuple; it pins `contracts.json`'s code table against
// `ALL_EXIT_CODES`), so translating them IN PLACE would replace the
// English the suite reads. They are keyed here instead, and merged at
// render time.
//
// Register: neutral Latin American Spanish with Mexican defaults --
// "computadora" not "ordenador", "archivo" not "fichero", second-person
// "tú" (the voice the English page already uses), no peninsular
// "vosotros". Where a Mexican reader and a Colombian one would say it
// differently, the sentence is rewritten so neither has to notice.
//
// NOT TRANSLATED, anywhere in this file: verb names, flag names, paths,
// module names, port names, exit-code NAMES, engine names, field names in
// JSON payloads, and the `-o table` / `-o json` / `-o ndjson` spellings.
// Those are the product's surface. A reader who types a translated flag
// gets exit 2, so inventing one would be worse than leaving it in
// English. The same rule governs the captured transcripts, which are not
// translated at all: they are bytes a real run printed.

/** Verb purposes, keyed by the verb's own (untranslated) name. */
export const VERB_PURPOSES_ES: Readonly<Record<string, string>> = {
  doctor:
    'Reporta el adaptador resuelto de cada puerto, su versión y una sugerencia de instalación acorde a tu sistema para lo que falte.',
  info: 'Número y tamaño de páginas, cifrado y bits de permisos, metadatos, productor, lista de fuentes, presencia de firma y rotación por página.',
  version: 'Reporta las versiones de la herramienta, del runtime y de los motores.',
  merge:
    'Concatena PDFs; selección de páginas por entrada con ruta:rango; una entrada de índice por archivo de origen.',
  split:
    'De un PDF a muchos, por tamaño fijo de bloque, por rangos explícitos, página por página o en los marcadores de primer nivel.',
  extract: 'Escribe las páginas seleccionadas en un PDF nuevo, en el orden indicado.',
  delete: 'Escribe todo excepto las páginas seleccionadas.',
  rotate: 'Rota las páginas seleccionadas en múltiplos de 90°, de forma absoluta o relativa.',
  reorder:
    'Reescribe el orden de las páginas a partir de una secuencia explícita; se permiten duplicados y se respeta el orden dado.',
  repair:
    'Recuperación estructural de un PDF dañado o mal formado con el analizador de recuperación de libqpdf.',
  linearize: 'Reescribe para entrega progresiva por bytes ("vista web rápida").',
  permissions: 'Reporta los bits de permisos y el algoritmo de cifrado de un PDF cifrado.',
  'meta get': 'Lee el diccionario de información del documento y el XMP.',
  'meta set': 'Escribe o limpia campos de información del documento y el XMP.',
  rasterize: 'De PDF a PNG/JPEG/TIFF/WEBP al DPI o ancho en píxeles que elijas.',
  compose:
    'De imágenes a PDF. Las entradas JPEG se incrustan como flujos DCTDecode (conservan los bytes, sin recodificar).',
  create: 'De texto (v1) a PDF. Markdown y HTML detrás del extra [html] (fase 2).',
  text: 'Extrae texto: ruta rápida (pdfium) o con reconocimiento de maquetación (pdfplumber), con geometría por bloque.',
  tables: 'Detecta y extrae tablas a CSV o JSON.',
  compress:
    'Reduce el tamaño: flujos de objetos de libqpdf más recompresión de flujos (sin pérdida) y, opcionalmente, reducción y recompresión de imágenes con Pillow (con pérdida).',
  encrypt:
    'Aplica AES-256 (o RC4-128 con --legacy) con contraseñas de usuario y de propietario, y un conjunto de permisos.',
  decrypt: 'Quita el cifrado cuando se da la contraseña correcta.',
  watermark: 'Superpone o subpone texto generado sobre las páginas seleccionadas.',
  stamp: 'Superpone o subpone una página de un PDF existente sobre las páginas seleccionadas.',
  ocr: 'Agrega una capa de texto de Tesseract sobre los píxeles intactos: se genera un PDF solo de texto por página y se une.',
  convert: 'De Office a PDF con LibreOffice en modo headless.',
};

/** Family names. The KEY is the untranslated family id the roster groups
 *  on; only the heading a reader sees is Spanish. */
export const FAMILIES_ES: Readonly<Record<string, string>> = {
  diagnostics: 'diagnóstico',
  structure: 'estructura',
  raster: 'rasterizado',
  compose: 'composición',
  text: 'texto',
  optimize: 'optimización',
  crypto: 'criptografía',
  overlay: 'superposición',
  external: 'externo',
};

/** Spine layers, keyed by the layer index (`L1`..`L6`). `path` and
 *  `enforcedBy` never appear here -- a test name is an identifier. */
export const LAYERS_ES: Readonly<
  Record<string, { name?: string; rule?: string; desc?: string; chip?: string; spawnChip?: string; forkNote?: string }>
> = {
  L1: {
    rule: 'La única capa que puede importar el framework de CLI.',
    desc: 'Interpreta las banderas, construye un solo OperationPlan inmutable y elige un renderizador.',
  },
  L2: {
    rule: 'Funciones simples, sin framework, que trabajan solo a través de los puertos de abajo. Aquí nunca se decide un rechazo del sistema de archivos.',
    desc: 'Sin entrada/salida salvo a través de Safety y Ports.',
    forkNote: 'Ops llega a Safety y a Ports en paralelo.',
  },
  L3: {
    chip: '1 ARCHIVO',
    rule: 'El único lugar que escribe en disco: un archivo, no un paquete. Las dos listas de permitidos de escritura están vacías.',
    desc: 'Escritura a temporal, fsync y rename atómico. Aquí vive la compuerta de --dry-run.',
  },
  L4: {
    chip: '6 puertos',
    rule: 'Solo definiciones de typing.Protocol. Importar todos los módulos de puertos no carga ningún motor.',
    desc: 'La forma que cada motor tiene que cumplir.',
  },
  L5: {
    chip: '8 módulos adaptadores',
    spawnChip: '+1 archivo que lanza procesos: subprocess_util.py',
    rule: 'El único paquete que puede importar una biblioteca de motor. subprocess_util.py es el único módulo del árbol que puede lanzar un proceso.',
    desc: 'Ocho módulos sirven a los seis puertos de arriba. El noveno archivo es el que tiene permiso de lanzar un programa, no el respaldo de un motor.',
  },
  L6: {
    rule: 'stdout es la carga útil; stderr es todo lo demás.',
    desc: 'Lo que devuelve Ops, renderizado como table, json o ndjson.',
  },
};

export const SPINE_ES = {
  enginesName: 'Motores',
  enginesNote: 'No son parte de este código. Solo licencias permisivas, verificadas en CI.',
  boundaryLabel: 'Frontera que se hace cumplir',
  boundaryAbove: 'sin importar motores, sin lanzar programas, sin escribir fuera del único archivo con permiso',
  boundaryBelow: 'todos los motores de terceros',
} as const;

/** Exit-code meanings, keyed by the code. The NAMEs (`OK`, `REFUSED`, …)
 *  are public API and stay in English on both pages. */
export const EXIT_MEANINGS_ES: Readonly<Record<number, string>> = {
  0: 'Éxito, incluido un reporte vacío pero válido. Un --dry-run refleja el código que devolvería la corrida real, así que no siempre es 0.',
  1: 'La operación se ejecutó y falló: entrada corrupta, error del motor o un destino donde no se puede escribir.',
  2: 'Invocación incorrecta: bandera desconocida, banderas mutuamente excluyentes, rango de páginas mal formado o subcomando desconocido.',
  3: 'Falta un motor o un binario requerido. El mensaje siempre trae una sugerencia de instalación.',
  4: 'Invocación válida, pero no hay nada sobre lo cual actuar.',
  5: 'Una compuerta de seguridad lo rechazó.',
  6: 'Falta la contraseña, es incorrecta o es del tipo equivocado.',
};

export const CONTRACTS_ES = {
  rules: [
    'Agrega un código; nunca renumeres uno.',
    'Romper esta tabla es un cambio de versión mayor, no un parche.',
  ],
  carveOuts: [
    {
      title: 'La excepción del código 0: el veredicto de un motor',
      text: 'convert y ocr le entregan el operando a un binario fuera del proceso (soffice o tesseract) y un --dry-run puede no llegar a iniciarlo. Cada elemento en seco de esos comandos lleva engine_verified: false en su detalle, así que la vista previa nunca se lee como un éxito sin reservas.',
    },
    {
      title: 'La excepción del código 0: si una contraseña es correcta',
      text: 'Si una contraseña se puede resolver es algo decidible con solo comprobar que existe, y una vista previa lo predice; si una contraseña ya resuelta es correcta solo se puede decidir intentándola, y una vista previa no debe convertirse en un oráculo. Cada elemento en seco que nombra una fuente de contraseña lleva password_verified: false en su detalle.',
    },
  ],
  /** Keyed by the flag itself, which is not translated. */
  shapes: {
    '-o table': 'Una tabla alineada en texto plano, para una persona leyendo una terminal.',
    '-o json': 'Un solo objeto, que lleva schema_version.',
    '-o ndjson':
      'Un objeto por elemento, uno por línea; cada línea lleva su propio schema_version.',
  } as Readonly<Record<string, string>>,
  asymmetry:
    'Los errores son la única asimetría deliberada: con -o table un error es un mensaje de una línea en stderr, pero con -o json o -o ndjson es un objeto en stdout, así que un consumidor automatizado que lee stdout nunca tiene que leer además stderr para enterarse de que una corrida falló.',
} as const;

/** Atomic-write stations, keyed by position (the glyph is a numeral and
 *  is the same mark in both languages). */
export const STATIONS_ES: readonly { name: string; detail: string }[] = [
  { name: 'Planear / rechazar', detail: 'Rechaza un destino que ya existe si no pasas --force. Código 5.' },
  { name: 'Compuerta de --dry-run', detail: 'Regresa antes de cualquier llamada al sistema de archivos, en ambos modos.' },
  {
    name: 'Archivo temporal',
    detail: 'Un archivo temporal junto al destino, en el mismo sistema de archivos: eso es lo que hace atómico el rename.',
  },
  { name: 'Escritura', detail: 'Escribir, vaciar el búfer, fsync.' },
  { name: 'Respaldo .bak', detail: 'Solo con --in-place.' },
  { name: 'os.replace()', detail: 'Atómico. El único punto donde las dos vías se tocan.' },
];

export const ATOMIC_ES = {
  failure:
    'Si algo falla en los pasos ① a ⑤: el temporal se elimina, tu archivo queda intacto y el proceso termina con un código distinto de cero.',
  crossingLabel: 'aquí cambia tu archivo',
} as const;

/** Worked examples, keyed by the example id. The SESSIONS are captures and
 *  are never translated. */
export const EXAMPLES_ES: Readonly<Record<string, { title: string; point: string; comment?: string }>> = {
  doctor: {
    title: 'Averigua qué está instalado de verdad',
    point:
      'Los motores son opcionales y se resuelven en tiempo de ejecución. Esto reporta qué encontró, en qué versión y qué falta, para que una máquina pueda decidir si un trabajo siquiera es posible antes de empezarlo.',
  },
  inspect: {
    title: 'Inspecciona un documento, pensando primero en la máquina',
    point:
      'No se pasó ninguna bandera. La salida es JSON porque stdout no es una terminal: el mismo comando es legible para una persona cuando lo corres tú, y analizable cuando lo corre un script.',
  },
  merge: {
    title: 'Haz el trabajo',
    point:
      'Un renglón por entrada, cada uno con su propio código de salida y su conteo de bytes. No se escribe nada hasta que se leyeron todas las entradas y se verificó el destino.',
  },
  refuse: {
    title: 'Falla de una forma sobre la que un script puede actuar',
    point:
      'Córrelo otra vez y se rehúsa en lugar de sobrescribir. El rechazo es un objeto estructurado con un código estable: no es un mensaje que haya que reconocer con expresiones regulares, ni una sobrescritura silenciosa.',
    comment: 'el código de salida coincide con la carga útil',
  },
};

/** Dependency roles for the licensing annex.
 *
 *  The twenty transitive rows all read "pulled in by <packages>", where
 *  the package list is identifiers. Those are translated by REWRITING THE
 *  PREFIX rather than by enumerating twenty near-identical strings: a new
 *  transitive dependency then arrives in Spanish automatically, instead of
 *  silently shipping an English row nobody notices until a reader does.
 *  The eleven direct rows say something specific and are enumerated. */
const ROLE_DIRECT_ES: Readonly<Record<string, string>> = {
  pypdf: 'unir, dividir, reordenar, rotar, metadatos, marcadores, superposición de marca de agua, cifrar y descifrar',
  pypdfium2: 'De PDF a imágenes, renderizado de páginas, extracción rápida de texto plano',
  reportlab: 'crear PDFs desde cero, de imágenes a PDF (incrustado DCTDecode sin pérdida)',
  pikepdf: 'reparar, linearizar, compresión de flujos de objetos, cifrado robusto',
  pdfplumber: 'texto con reconocimiento de maquetación, tablas',
  'pdfminer-six': 'el motor de análisis de maquetación detrás de pdfplumber',
  pytesseract: 'controlador de OCR para el binario tesseract',
  pillow: 'manejo de imágenes y reducción de resolución para comprimir',
  weasyprint: 'De HTML/Markdown a PDF, opcional (extra [html], fase 2)',
  typer: 'la superficie de la CLI',
  cryptography: 'cifrado AES-256 que respalda a pypdf[crypto]',
};

const PULLED_IN_BY = 'pulled in by ';

/** Translate one role cell. Falls back to the English text rather than to
 *  an empty cell, so a role this file has not caught up with still says
 *  something true. */
export function roleEs(normalizedName: string, role: string): string {
  const direct = ROLE_DIRECT_ES[normalizedName];
  if (direct) return direct;
  if (role.startsWith(PULLED_IN_BY)) return `lo trae ${role.slice(PULLED_IN_BY.length)}`;
  return role;
}

/** Install-tier badges, keyed by the English label the badge function
 *  returns. `[html]` is the extra's real spelling and stays. */
export const TIERS_ES: Readonly<Record<string, string>> = {
  'default install': 'instalación por omisión',
  'optional · [html] extra': 'opcional · extra [html]',
  'build tooling': 'herramientas de compilación',
};
