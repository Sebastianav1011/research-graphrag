# Revisión semántica y exploración complementaria controlada

Estado: implementación local probada con transporte sintético; ejecución institucional
complementaria y aceptación pendientes. No cambia ASSESSMENT_V2 ni
EVIDENCE_CONFIDENCE_V2. No modifica Capas 1–3 ni 4B.

## Qué cambió y qué permanece histórico

`semantic_fallback.py` utiliza `CodexCliAssessmentProvider`, el schema V2, las
validaciones literales y el cálculo Decimal existentes. La política suplementaria
`SEMANTIC_POLICY_V2_1` agrega instrucciones, por lo que una respuesta con la política
anterior no se presenta como una evaluación realizada bajo las nuevas instrucciones.
Los resultados iniciales compatibles se conservan como observaciones históricas
reutilizadas; solo se reevalúan pares identificados expresamente para corregir una
discrepancia, y los proyectos todavía pendientes se evalúan con la nueva política.
La vista efectiva reemplaza lógicamente los pares corregidos sin editar sus originales.

La fórmula permanece `100 * (0.55 * (strength / 4) + 0.45 * K)`, con
CLEAR=1, PARTIAL=0,5, NOT_DEMONSTRATED=0. Todos los estados válidos tienen score;
INVALID_ASSESSMENT conserva NULL. No es probabilidad ni reclasifica por umbral.

La aclaración responde a una debilidad observada de interpretación, sin afirmar que
el contrato V2 impusiera siempre un impacto final: la temporalidad requerida se
interpreta desde la definición. Promoción de capacidades puede acreditarse mediante
acciones habilitantes documentadas y vinculadas a esa capacidad, sin ingresos ya
obtenidos. Una intención futura no demuestra que la acción haya ocurrido. La creación
de una red y la consolidación de relaciones se contrastan según las acciones y
mecanismos documentados, sin imponer antigüedad o formalización inexistentes en el
perfil. Las citas con temporalidad mixta se separan en fragmentos cuando sea posible.
Esto es una instrucción general, no una regla por indicador o project_id.

## Revisión humana encontrada

Se leyó, sin modificar, el workbook vigente `revision_humana_v2.xlsx`. Sus ocho
notas de acuerdo son: ASC-01=5, SAL-01=4, SAL-02=1, DIV-01=3, DIV-02=4,
COL-01=5, ECO-07=1 y SOC-02=1. Son grados de acuerdo, no etiquetas semánticas,
autorizaciones ni aceptación académica concluida.

| Caso | Resultado histórico | Qué requiere revisar |
|---|---|---|
| ECO-07 | INSUFFICIENT_EVIDENCE; strength 2, K 0,6, confianza 54,50 | Varios criterios exigen RESULT_DEMONSTRATED en la respuesta histórica; comprobar si esa exigencia excede la promoción de capacidades mediante actividades o mecanismos que realmente exige el perfil. No deducir capacidades ejecutadas de beneficios futuros. |
| SOC-02 | INSUFFICIENT_EVIDENCE; strength 2, K 0,625, confianza 55,63 | La frase que afirma una red establecida acredita existencia; analizar si el texto completo además describe fortalecimiento o funcionamiento colectivo. La creación por sí sola no equivale automáticamente a consolidación. |
| SAL-02 | NOT_SUPPORTED; strength 0, K 0, confianza 0 | El desacuerdo humano relaciona documentación técnica con un resultado médico; comprobar si existe una acción preventiva vinculada a un riesgo poblacional. Relación potencial con salud no demuestra prevención. |

No se convirtió ninguno de estos desacuerdos en SUPPORTED y no se ha ejecutado una
reevaluación institucional bajo la nueva política. Los comentarios originales permanecen
intactos. La eficacia de la aclaración todavía debe contrastarse en el piloto autorizado.

## Flujo y límites

1. Se preservan hasta dos candidatos iniciales publicados por Capa 3 por proyecto.
2. Se validan sus assessments y, cuando existan, las correcciones expresamente pedidas.
3. El fallback se activa únicamente si ninguna evaluación inicial efectiva es SUPPORTED.
   No se activa sobre assessments inválidos o inciertos.
4. El catálogo elegible utiliza categorías iguales o dimensiones no nulas iguales a las
   de los candidatos iniciales. Un NULL no relaciona categorías ajenas. Se prefieren
   los candidatos adicionales ya publicados para el proyecto, en su orden congelado;
   después se prioriza la misma familia categoría+dimensión y el id estable.
5. Se transmite como máximo un catálogo acotado de cinco perfiles por proyecto a Codex.
   La afinidad de metadatos limita presupuesto, no demuestra relevancia ni cumplimiento.
6. Codex devuelve una selección explícita de cero, uno o dos candidatos, con razón y
   citas sustantivas originales. Python verifica ids, límites y pertenencia literal.
7. Únicamente los seleccionados pasan al assessment V2 completo con los seis campos,
   perfil, rúbrica y reglas textuales. No se implementan reglas RULE_TEXT como evaluadores.
8. Se conserva una sola ronda. No se repiten pares, no se explora de nuevo al recibir
   NOT_SUPPORTED y no se fuerza SUPPORTED. El mecanismo es desactivable.

La exploración mantiene candidatos `LAYER4_SEMANTIC_FALLBACK` incluso cuando también
existían fuera del máximo inicial de retrieval. La evaluación inicial o su corrección
conservan `LAYER3_RETRIEVAL`. La publicación de Capa 3 no se altera. El pool es
deliberadamente incompleto: el límite de cinco y su orden pueden omitir otros indicadores
válidos. El piloto debe determinar beneficio/costo antes de aprobarlo para el cierre.

## Integridad, autorización y reanudación

La preparación utiliza la verificación de la ejecución vigente, conserva hashes de
fuentes, catálogo, código, prompts, schemas, resultados originales y runtime; no invoca
inferencia. `plan.json` incluye el inventario completo y su hash liga la autorización.

`authorization.example.json` es una plantilla **sin aprobar**. Se requiere una nueva
autorización de scope `semantic_fallback`, texto institucional autorizado, hash exacto
del plan, project_ids explícitos y fases autorizadas. Puede cubrir un subconjunto del
plan, por ejemplo los cinco proyectos piloto, sin autorizar los otros quince. La
autorización histórica del piloto V2 no habilita estas llamadas nuevas.

Cada invocación procesa como máximo cinco proyectos autorizados y no terminados. Hay
lock exclusivo; cada fase tiene carpeta de llamadas y registro propio. Una carpeta de
llamada sin registro completo produce UNCERTAIN_OUTCOME y detiene la reanudación;
no se reenvía automáticamente el texto. Un assessment inválido tampoco se reinfiere
automáticamente. Las fases ya completadas se reutilizan con sus hashes originales y
sin atribuirles nuevo consumo. Se comprueba la respuesta original frente al registro,
el prompt y schema usados, así como la recomputación de la confianza y del disparador.

## Mediciones y comparación

`verify` y `comparison` separan `initial`, `correction`, `exploration` y
`additional_assessment`. Conservan llamadas, tokens de entrada/salida/cacheados/total,
CPU y RAM del coordinador, tiempos, errores y reintentos del adaptador. Los tokens
no disponibles permanecen NULL; no se estiman por caracteres ni se inventan costos.
La duración por fase utiliza unión de intervalos, evitando sumar concurrencia como
duración de pared. La CPU/RAM local nunca representa recursos de servidores remotos.
Las llamadas de exploración no se cuentan como assessments.

`comparison.json` privado diferencia la distribución original y efectiva, propuestas,
evaluaciones nuevas, nuevos SUPPORTED con sus citas y fases de consumo. La revisión
de falsos positivos y el beneficio permanecen PENDING hasta revisión humana. El informe
académico de desempeño original se conserva y las mediciones nuevas solo se incorporan
cuando hayan ocurrido. Las pruebas sintéticas no se reportan como consumo institucional.

La publicación oficial usa todos los pares efectivos válidos, sin umbral de confianza,
y exige veinte proyectos distintos completos, aprobación ligada a política, plan y
resultados, y revisión humana de cada par efectivo. La revisión vigente admite una nota
de acuerdo 1–5 por par y comentario opcional; identidad y fecha del revisor se registran
una vez. La aceptación debe declarar explícitamente que las discrepancias se resolvieron
y aportar una referencia a esa resolución. No se convierten notas en etiquetas, métricas
de clasificación ni aceptación automática. El formato histórico de etiquetas independientes
sigue disponible como alternativa. El workbook final permanece bloqueado hasta cumplir
esas condiciones.

## API e integración

- `prepare(root, config_path, out, options_value=..., correction_pairs=..., include_remaining=False)`.
- `execute(root, out, authorization, batch_size=5)`; llamadas reales solo con autorización nueva.
- `verify(root, out)` y `comparison(root, out)`; verificaciones sin inferencia.
- `effective_rows(root, out)`; vista lógica con procedencia explícita.
- `publication_check(root, out, approval, review)`; gate final de ejecución y aceptación.

Las opciones predeterminadas desactivan fallback; presupuesto máximo adicional 2,
pool máximo 5, disparador único NO_SUPPORTED, timeout 600 segundos. Los entrypoints
integrados están en `scripts/run_layer4_closure.py`; el runner V2 original se preserva.
