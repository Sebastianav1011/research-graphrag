# Contrato de confianza PROJECT + INDICATOR

RAW_CONFIDENCE_V1 se conserva como versión histórica. La propuesta de cierre
[EVIDENCE_CONFIDENCE_V2](layer4_assessment_v2_contract.md) elimina F/C de la fórmula
y requiere contraste real y aprobación humana; todavía no está aceptada.

Versión: **RAW_CONFIDENCE_V1**. Alcance: lógica aislada de Capa 4 para validar un
assessment estructurado y medir la fuerza de su evidencia observable. El módulo
no produce assessments, no consulta proveedores ni consume outputs publicados.

## Frontera y significado

La futura LLM interpreta; el código valida; el sistema calcula la confianza.
Nunca se pide a una LLM que genere `confidence_raw_score`.
El contrato es independiente de modelo local, Codex CLI o API.

`discovery_chunk != evidence`, `retrieval_score != confidence` y
`candidate_source != indicator_match` siguen vigentes.
Capa 3 permanece cerrada como SOURCE_INDICATOR_V1. Este paquete no modifica
Capa 1/2/3, perfiles pendientes, manifests, retrieval, ranking ni territorios.

`confidence_raw_score` es un score de evidencia estructurada de 0.00 a 100.00.
**No es una probabilidad estadística ni una medida de exactitud.**
`confidence_probability` y `confidence_level` siempre son NULL.
No hay thresholds HIGH/MEDIUM/LOW ni calibración operacional.

## API y datos de entrada

Paquete: `src/layer4_confidence`. Funciones:

- `validate_assessment(project_fields, indicator_profile, assessment)`: lista
  ordenada de errores; vacía cuando supera las validaciones disponibles.
- `calculate_confidence_components(..., config=None)`: K/F/C/S como Decimal,
  solo para SUPPORTED válido y computable; en otro caso lanza ValueError.
- `calculate_raw_confidence(..., config=None)`: resultado estructurado con estado,
  componentes, raw score, campos reservados y errores.
- `load_confidence_config(path=...)` / `validate_confidence_config(config)`:
  cargan o validan la configuración local, sin mutar el argumento.

`project_fields` es un mapping explícito de nombres canónicos a valores reales.
Los textos son strings o NULL; `keywords` admite la lista de strings del contrato
canónico y también su representación textual explícita. Una cita sobre una lista
debe existir dentro de un ítem; no se concatenan ítems para fabricar citas.
Solo se inspeccionan los campos citados; otros atributos se ignoran.

`indicator_profile.key_elements` es una lista explícita de elementos clave.
`preferred_evidence_fields` es una lista explícita opcional de nombres permitidos.
No se infieren a partir de texto libre ni se reutiliza automáticamente la reserva
`preferred_substantive_fields` de Capa 3. Listas de campos desconocidos o tipos
incorrectos invalidan el assessment. Perfil ausente/malformado también lo invalida.
Elementos duplicados del catálogo y del assessment se cuentan una sola vez.

El assessment requiere `decision`, `support_strength`,
`supported_key_elements`, `evidence` y `explanation` (string no vacío).
Los dos arrays pueden estar vacíos en decisiones sin asignación.
La validación estructural y semántica normativa es la de Python; los JSON Schemas
en `schemas/layer4_confidence` describen las formas de intercambio. Validar solo
el schema no verifica citas, pertenencia al catálogo ni los demás hard gates.
Los metadatos adicionales se ignoran, incluidos scores proporcionados accidentalmente.

## Hard validation gates

- NOT_SUPPORTED exige strength entero 0; INSUFFICIENT_EVIDENCE exige 1 o 2;
  SUPPORTED exige 3 o 4. Bool, float y strings no se convierten a enteros.
- SUPPORTED exige elementos soportados no vacíos y pertenecientes exactamente
  al catálogo, al menos una cita y al menos un campo sustantivo con cita válida.
- Cada evidencia declara un campo permitido, presente realmente en el proyecto,
  y texto no vacío que existe dentro de ese campo. Todas las citas se validan,
  también para las decisiones sin asignación. Cualquier cita inventada invalida
  el assessment entero; nunca se compensa bajando el score.
- Orientación: `title`, `keywords`. Solo estos campos nunca justifican SUPPORTED.
  Sustantivos: `summary`, `methodology`, `objectives`, `expected_results`.
- Comparación determinística: Unicode NFC, colapso de secuencias de whitespace
  a un espacio y eliminación de whitespace exterior. Se preservan acentos,
  mayúsculas y puntuación. Substring literal para citas; igualdad para elementos.
  No fuzzy matching, embeddings, similitud semántica ni LLM. Los originales no cambian.

Si `key_elements` falta, es NULL o [], no hay denominador para K. Se difieren
únicamente la pertenencia y el mínimo de elementos soportados porque no existe
catálogo contra el que verificarlos. Los tipos y todos los demás gates siguen
vigentes: un SUPPORTED con cita inventada continúa siendo INVALID_ASSESSMENT.
Un SUPPORTED que supera los otros gates es NOT_COMPUTABLE, incluso si declaró
elementos cuya pertenencia aún no puede verificarse. Nunca se crea una asignación
con score computado sin catálogo.

## Fórmula y configuración

`config/layer4_confidence.yaml` define versión, pesos, relevancias, corroboración
y clasificación cerrada de campos. Se rechazan claves YAML duplicadas. Se valida versión, estructura, valores finitos
en [0,1] y suma Decimal de pesos exactamente igual a 1.0. Una configuración errónea
lanza ValueError: es un error del sistema, no una cita inválida.
Se pueden suministrar pesos válidos explícitos mediante `config=`; la
configuración versionada distribuida define la fórmula oficial de esta versión.
Cambiar la política publicada requiere una nueva versión del contrato.

```text
confidence_raw_score = 100 * (0.35*K + 0.30*F + 0.20*C + 0.15*S)
```

| Componente | Cálculo |
|---|---|
| K | Elementos soportados únicos / elementos únicos del indicador |
| F | Máxima relevancia de todos los campos con citas válidas |
| C | Corroboración por campos sustantivos distintos |
| S | support_strength / 4 |

F: con preferencias no vacías, campo sustantivo preferido = 1.00; otro
sustantivo = 0.75. Sin preferencias (ausente, NULL o []), sustantivo = 1.00.
Orientación siempre = 0.25, aunque figure en preferencias. Nunca se promedian
campos fuertes con débiles.

C: cero campos sustantivos = 0.00; uno = 0.70; dos o más = 1.00.
Varias citas del mismo campo no aumentan corroboración. Title/keywords no cuentan.

Ninguna parte usa vector_score, cosine_score, graph_score, hybrid_score, rank,
retrieval_score ni similitud BGE-M3.

La carga YAML conserva decimales sin pasar por float. Componentes y fórmula usan
Decimal con contexto local de precisión 50; el raw score se cuantiza a 0.01 con
ROUND_HALF_UP. La API devuelve Decimal (p. ej. Decimal('87.50')), no float.
Un futuro adaptador JSON deberá serializar sus valores como números; el formato
de presentación con dos decimales es responsabilidad de ese límite de transporte.
No se implementa ningún adaptador de proveedor en esta fase.

## Estados y resultado

| Caso | confidence_status | confidence_raw_score |
|---|---|---|
| SUPPORTED válido y catálogo disponible | COMPUTED | Decimal 0.00–100.00 |
| INSUFFICIENT_EVIDENCE o NOT_SUPPORTED válidos | NOT_APPLICABLE | NULL |
| SUPPORTED válido, sin elementos clave configurados | NOT_COMPUTABLE | NULL |
| Error de validación | INVALID_ASSESSMENT | NULL |

Solo COMPUTED contiene componentes; los demás devuelven los cuatro como NULL.
La precedencia es validación, aplicabilidad, disponibilidad de catálogo, cálculo.
`validation_errors` solo contiene errores en INVALID_ASSESSMENT.

Ejemplo obligatorio: strength=3, 3/4 elementos, objectives + expected_results
preferidos: K=0.75, F=1.00, C=1.00, S=0.75, raw score=**87.50**.

## Fase posterior

Un benchmark humano permitirá evaluar exactitud, observar falsos positivos,
calibrar el raw score y producir confidence_probability. La revisión humana
servirá exclusivamente para benchmark/calibración; no formará parte del pipeline
operacional final. Aquí no se implementa calibración, se entrena un modelo,
se ejecuta assessment real ni se genera una muestra de proyectos.
