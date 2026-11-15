# Auditoría de rigurosidad y preparación del piloto PROSPECTIVE_V2

## Alcance y conclusión

Se revisaron las dos notas de V2, los 48 perfiles/rúbricas del run **`run_20261115_063255_909981`** y las funciones directamente implicadas en políticas, prompts, validación, confianza, transporte y exportación. No se buscaron otros runs, no se recorrió `incoming` y no se ejecutaron proyectos, inferencias o reconstrucciones.

La instrucción más reciente pide **preparar el piloto sin modificar rúbricas**. Por ello no se alteran criterios, roles, reglas de V2 ni sus instrucciones de producción. Los cambios implementados son un ejecutor aislado, comparación automática y pruebas deterministas. **No se crea una revisión metodológica nueva porque no se modifica la metodología.** Queda preparada `PROSPECTIVE_V2`, contrato `ASSESSMENT_PROSPECTIVE_V2`, prompt `PROSPECTIVE_V2_APPLICABILITY_V1`. `TWO_PAIR_PROSPECTIVE_V2_PILOT_V1` identifica únicamente el protocolo del piloto.

**SUPPORTED es alcanzable**, pero no se puede asegurar aún que Qwen vaya a interpretar mejor los proyectos. El cero de resultados positivos del run de diagnóstico pertenece a **PROSPECTIVE_V1** y no constituye evidencia de que V2 haya fallado. No se ha ejecutado una campaña V2.

## Restricciones y riesgos comprobados

1. **No hay una exigencia global de ejecución heredada de V1 en los prompts efectivos V2.** La derivación transforma las etapas y sustituye los argumentos que exigían ejecución. Las pruebas inspeccionan los 48 prompts, no solo el texto de las constantes. Objetivos, métodos y resultados esperados concretos son evidencia sustantiva válida.
2. **Persisten dos excepciones explícitas, no globales:** `DIV-03` y `POL-02`. `prospective_v2.py::EXTERNAL_RECORD_CRITERIA` exige observaciones para determinados registros externos. Por tanto, no corresponde describir V2 como completamente prospectiva para esas condiciones. La justificación conservadora es no inventar menciones ni citas de terceros; existe una asimetría metodológica frente a adopción o valoración previstas en otros indicadores. Resolverla requiere una revisión versionada y validación humana, no un ajuste dirigido a aprobar estos dos proyectos. El piloto TEC-04 no está sujeto a esas excepciones.
3. **233 criterios REQUIRED y 13 COMPLEMENTARY en 246 criterios.** No hay grupos ALTERNATIVE externos en esta rúbrica; varias disyunciones están dentro de un criterio. Muchos REQUIRED aumentan la sensibilidad a falsos negativos, pero su número no demuestra que sobren condiciones. El código no exige documentos distintos para cada criterio: una cita sustantiva puede respaldar varios. No se eliminan conjunciones ni condiciones institucionales a partir de la mera existencia de resultados humanos favorables.
4. **Posibles solapamientos que requieren juicio metodológico:** COL-01/C04 respecto de la integración ya descrita en C01–C03; TEC-04/C03 y C05 respecto de función y fundamento de la tecnología; indicadores de nivel/conteo respecto de delimitación y descripción del grado. No hay prueba suficiente para reclasificarlos automáticamente como secundarios. Las etiquetas complementarias existentes no bloquean SUPPORTED. La matriz identifica límites concretos para cada indicador.
5. **La aplicabilidad es una puerta independiente.** Falta de citas o afinidad temática no justifican NOT_APPLICABLE. La aplicabilidad indeterminada puede mantener insuficiencia, sin confundirla con un error técnico. NOT_APPLICABLE exige citas y explicación de alcance incompatible; no utiliza umbrales de confianza.
6. **La confianza no resuelve la clasificación.** Se conserva exactamente `C = 100 × (0,55 S + 0,45 K)` y el cálculo SK existente. Una prueba obtiene **94,38** con un requisito esencial parcial y mantiene INSUFFICIENT_EVIDENCE. No se modifica S, K, pesos, redondeo o umbrales. La nota categórica `support_strength` no es el componente S ni el porcentaje calculado.
7. **La comprobación semántica tiene límites.** El contrato rechaza apoyo sustantivo declarado contextual/ajeno y referencias exclusivamente CONTEXT. No puede detectar por sí solo que Qwen haya etiquetado erróneamente una cita como PROJECT_CONTRIBUTION o RESULT_DEMONSTRATED. El texto genérico sobre límites externos, compartido en las instrucciones, podría ser extrapolado indebidamente por el modelo a otros indicadores. Estas posibilidades se documentan para revisión posterior, sin modificar el prompt antes del piloto solicitado.

Las funciones revisadas son `assessment_v3.py::{evaluation_policy,catalog_for_mode,validate,confidence}`, `prospective_v2.py::{derive,validate}`, `context_budget.py::make_request`, `evidence_references.py::{response_schema,materialize}`, `live_execution.py::{request_for,check_wrapper,execute}`, `ollama_provider.py::{evaluate,corrective_request}` y los exportadores de tesis existentes.

## Antecedentes de Excel, sin usarlos como etiquetas de aprobación

Se leyeron sin guardar cambios [Validación 2026.xlsx](<C:/Users/sebas/Downloads/Validación 2026.xlsx>) y [resultado_final.xlsx](<C:/Users/sebas/Downloads/resultado_final.xlsx>).

- `Validación 2026.xlsx`, `Descriptores!A2:V10`: nueve proyectos con marcas por familias de indicadores. `V5`, `V6`, `V8`, `V9` y `V10` señalan omisiones respecto del análisis humano. Estas observaciones son antecedentes de posibles falsos negativos; las marcas no especifican las 48 decisiones individuales ni proporcionan un benchmark completo.
- `resultado_final.xlsx`, `INDICADORES!A2:I422`: 421 filas, con 25 SUPPORTED, 170 INSUFFICIENT_EVIDENCE, 181 NOT_SUPPORTED y 45 REVIEW_REQUIRED. Son resultados favorables anteriores, no una verdad documental independiente. Algunas justificaciones afirman ejecución o se refieren al «catálogo» como evidencia; requieren revisar su atribución a las fuentes originales antes de considerarlas correctas.
- Los proyectos de esos antecedentes no son los dos del piloto. No se ajustaron criterios para reproducir las etiquetas de esos archivos, no se compararon contra otros runs y no se intentó reproducir sus resultados.

## Matriz de revisión de los 48 indicadores

Rúbrica candidata conservada, no nueva adjudicación humana. C = identificación contextual; P = propuesta/diseño/mecanismo o etapa superior; E = resultado esperado o demostrado. Las observaciones no sustituyen las [definiciones y adaptaciones documentadas](prospective_v2_catalogo.md). En todos los casos siguen siendo necesarias citas específicas, pertinentes y atribuibles al proyecto.

| Indicador | REQUIRED / COMPLEMENTARY | Etapas efectivas | Revisi?n metodol?gica |
|---|---:|---|---|
| AMB-01 | 4 / 0 | C, P | Solucion prevista con funcion ambiental; no exigir adopcion o mejora medida. |
| AMB-02 | 5 / 0 | C, E | Preservar las tres dimensiones; admitir cambios esperados explicados. Riesgo: confundir sostenibilidad con resultado ya observado. |
| ASC-01 | 5 / 0 | C, P | Dialogo previsto reciproco; identificar actores no prueba intercambio. Una cita puede respaldar varios criterios. |
| ASC-02 | 4 / 0 | C, E | Ruta prevista de uso/adaptacion/sostenimiento; no exigir uso ocurrido ni aprobar por mera entrega. |
| ASC-03 | 6 / 0 | C, E, P | Pertinencia, comprensibilidad, calidad y valoracion son distintas. Revisar coherencia con limites de respuestas externas de DIV-03/POL-02. |
| COL-01 | 4 / 0 | P | C04 puede solaparse con C01-C03. No exigir una segunda prueba independiente ni analisis ejecutados; roles requieren revision humana antes de relajarlos. |
| COL-02 | 4 / 1 | C, P | Papeles y etapas previstos bastan; C05 es complementario y no puede bloquear. |
| COL-03 | 5 / 0 | C, P | Incidencia y etapas previstas. C05 no autoriza inventar una escala numerica de participacion. |
| CUL-01 | 4 / 1 | C, E | La poblacion no demuestra fortalecimiento cultural. C05 es complementario; revisar interpretacion de la enumeracion de procesos. |
| CUL-02 | 3 / 1 | C, P | Una via pertinente de conservacion/valorizacion/enriquecimiento; no exigir todas. C04 complementario. |
| DIV-01 | 5 / 0 | C, E, P | Estrategia concreta y eficacia esperada fundamentada; no exigir audiencia ya alcanzada. |
| DIV-02 | 5 / 1 | C, E, P | Identidad, uso y publicos previstos; conteos son metas documentadas. C06 complementario. |
| DIV-03 | 5 / 0 | C, E, P | EXCEPCION: C02/C04 requieren registro externo observado. No es una modalidad plenamente prospectiva para este par de condiciones; no cambiar para el piloto. |
| DIV-04 | 7 / 0 | C, E, P | Consulta y aprovechamiento esperados requieren mecanismos, no analiticas de uso ocurridas. C07 no permite inventar escala. |
| DIV-05 | 5 / 0 | C, E, P | Espacios previstos fuera de la academia; contar unidades distintas, no asistentes. |
| ECO-01 | 5 / 0 | C, E, P | Ingresos adicionales esperados con receptor y via concreta; no exigir ventas realizadas. |
| ECO-02 | 5 / 0 | C, E, P | Ahorro previsto y referencia pertinente; no imponer cifra o ensayo si el catalogo no lo exige. |
| ECO-03 | 4 / 1 | C, E | Oportunidad laboral prevista concreta; no exigir puesto ya ocupado. C05 complementario. |
| ECO-04 | 5 / 0 | C, E | Fortalecimiento previsto de eslabon pertinente; no exigir toda la cadena ni ingreso final. |
| ECO-05 | 5 / 0 | C, E | Mejora productiva sostenible prevista; estudiar sostenibilidad no basta. |
| ECO-06 | 6 / 0 | C, E | Crecimiento esperado con referencia; no exigir simultaneamente TIR, ingresos y calidad de vida ni una escala inventada. |
| ECO-07 | 5 / 0 | C, E, P | Red colaborativa o estrategia solidaria prevista con funcion productiva; no exigir las dos vias. |
| POL-01 | 5 / 0 | C, P | Participacion facilitada prevista en politica o ciencia ciudadana; no exigir norma modificada. |
| POL-02 | 4 / 2 | C, P | EXCEPCION: C01/C02/C05 requieren observacion externa. Asimetria con adopcion prevista en otros indicadores; pendiente de decision metodologica versionada. |
| POL-03 | 5 / 0 | C, P | Ruta prevista concreta de modificacion/implementacion y contribucion; recomendacion generica no basta. |
| POL-04 | 5 / 1 | C, P | Ruta prevista de adopcion estatal; entrega no prueba adopcion. C06 complementario. |
| POL-05 | 5 / 1 | C, P | Audiencia y participacion previstas con unidad de registro; C06 complementario, sin exigir participacion pasada. |
| POL-06 | 4 / 1 | C, P | Colaboracion conjunta prevista con actores identificados; C01 complementario no bloquea. |
| POL-07 | 6 / 0 | C, P | Documentos y entrega previstos a gobierno; identidad/conteo no exigen recepcion ocurrida. |
| POL-08 | 5 / 1 | C, P | Organizacion prevista y destinatarios funcionarios; no exigir evento realizado. C05 complementario. |
| POL-09 | 5 / 0 | C, P | Participacion o creacion prevista de red multisectorial; no exigir ambas vias o cambio de politica. |
| SAL-01 | 6 / 0 | C, E | Conservar bienestar fisico y mental; explicar aportes previstos por dimension, sin exigir mejora observada. |
| SAL-02 | 5 / 0 | C, P | Riesgo poblacional y mecanismo preventivo previstos; poblacion clinica no prueba prevencion. |
| SAL-03 | 4 / 0 | C, E, P | Accion prevista dirigida a discapacidad y proposito de calidad de vida; no exigir mejora medida. |
| SAL-04 | 6 / 0 | C, E, P | Tasa de mortalidad esperada con referencia poblacional/temporal; no sustituir tasa por riesgo o muertes absolutas. |
| SAL-05 | 6 / 0 | C, P | Articulacion prevista entre saberes y actores; no exigir eficacia clinica ni subordinacion de una medicina. |
| SAL-06 | 5 / 0 | C, E, P | Estrategia participativa y fortalecimiento previstos; no exigir estrategia ya implementada. |
| SOC-01 | 5 / 0 | C, E | Mejora esperada y mecanismo de contribucion; no exigir atribucion causal ya demostrada. |
| SOC-02 | 4 / 0 | C, E, P | Acciones previstas que consolidan red; una lista de entidades no demuestra colaboracion. |
| SOC-03 | 5 / 0 | C, E, P | Respuesta prevista a desigualdad/exclusion/injusticia; estudiar poblacion vulnerable no basta. |
| SOC-04 | 5 / 0 | C, E | Beneficio, recepcion y conteo previstos; no identificar automaticamente muestra con beneficiarios. |
| TEC-01 | 4 / 0 | C, P | Producto tecnologico previsto y aporte de actores aplicados; no exigir comercializacion. |
| TEC-02 | 4 / 1 | C, P | Prueba participativa prevista con usuarios destinatarios; C05 complementario; no exigir validacion realizada. |
| TEC-03 | 4 / 1 | C, E | Producto y potencial comercial previstos fundamentados; no exigir ventas. C05 complementario. |
| TEC-04 | 5 / 0 | C, E, P | Uso instrumental, destinatarios, funcion y mecanismo previstos. C03/C05 pueden compartir cita; no exigir dos mecanismos ni impacto maximo medido. |
| TEC-05 | 4 / 0 | C, E, P | Originalidad y ruta prevista de aplicacion extraacademica; no afirmar demostracion ocurrida ni pedirla como requisito temporal. |
| TEC-06 | 6 / 0 | C, P | Aplicacion prevista novedosa y contextual; no exigir tecnologia original ni solucion total. |
| TEC-07 | 5 / 0 | C, E, P | Adopcion/adaptacion/sostenimiento previstos por actor externo; no exigir las tres vias o adopcion ocurrida. |

## Cambios implementados y validación

- `scripts/pilot_prospective_v2.py`: prepara solo dos pares, sella el código/política y comprueba la identidad de los manifiestos del Knowledge. Conserva las rúbricas V2 existentes. No instancia ningún cliente durante `prepare`.
- La ejecución manual reutiliza `live_execution.execute`: proveedor real de Qwen, validaciones de citas, criterios, decisiones y etapas, cálculo existente y conservación de respuestas nativas. No hay respuestas simuladas en el ejecutor del piloto.
- Se reutilizan exactamente los fragmentos y relaciones recuperados del run indicado. No se realiza otra recuperación o inferencia BGE-M3. Esto controla la evidencia para atribuir diferencias a la evaluación V2; no mide si una recuperación nueva mejoraría el contexto.
- El máximo es cuatro llamadas nativas: dos iniciales y un reintento por par si hace falta. Se conservan modelo, configuración general y reglas de aceptación. El presupuesto reducido de reintentos es una propiedad del piloto, no un cambio metodológico.
- Se exportan únicamente evaluaciones válidas. Un bloqueo o falta de resultado conserva decisión y confianza nulas. La comparación conserva respuestas, validaciones, citas, criterios esenciales incompletos y aplicabilidad. Un nuevo SUPPORTED queda pendiente de comprobar documentalmente.
- `tests/test_prospective_v2_pilot.py`: preparación sin contacto a Ollama, inmutabilidad del plan, alcance estricto, informe sin resultados inventados, confianza alta con esencial parcial, no aplicabilidad documentada, 48 prompts y clasificación prudente de cambios. Se reutiliza además `tests/test_prospective_v2.py` para propuestas concretas, intención vaga, fórmula exacta, exportaciones y fallos técnicos.

**Resultado:** 53 pruebas deterministas aprobadas en esos dos archivos. No se ejecutó Qwen, no se crearon agentes ni servidores y no se alteraron los resultados del run de referencia. La disponibilidad de Ollama y las decisiones reales de los dos pares siguen sin comprobarse hasta la ejecución manual.

## Pendiente de validación humana y selección de versión

La revisión humana debe decidir si los solapamientos identificados introducen obligaciones nuevas, si los límites de registros externos deben generalizarse o adaptarse prospectivamente y si las disyunciones/indicadores cuantitativos se están interpretando con rigor. No basta aumentar positivos: hay riesgo de confundir metodología con acción aplicada, población con beneficio, colaboración nominal con incidencia o una expectativa con un logro ocurrido. A la inversa, exigir realización o varias citas independientes puede generar falsos negativos.

La versión preparada es **PROSPECTIVE_V2 sin revisión metodológica adicional**. Para un run posterior del pipeline se selecciona `--evaluation-mode prospective-v2`. Para este piloto, usar exclusivamente el [comando manual del piloto](piloto_prospective_v2.md); ya tiene modo V2, TEC-04 y los dos proyectos fijados, sin procesar proyectos completos. Antes de ejecutarlo, `comparacion.md` solo informa que el piloto está preparado. Al terminar se convierte en el informe comparativo; no existen resultados nuevos anticipados.
