# Monitoreo y lotes de indicadores

**Estado al cierre del 8 de noviembre de 2026:** pruebas reales suspendidas por
instrucción del usuario. No iniciar ni reanudar GraphRAG, embeddings o inferencias
sin una nueva autorización explícita. Una autorización antigua guardada en disco
no sustituye esa autorización. Los comandos de ejecución de este documento son
solo referencia para una futura ejecución personal del usuario.

Los lotes siguen siendo experimentales: la comparación histórica muestra
discrepancias semánticas que requieren revisión humana. No se certifica todavía
la conservación de calidad ni se recomienda ejecutar los 100 proyectos con lotes.
Véase el [informe de revisión estática](status/optimization_static_review_20261108.md).

`status` autónomo consulta SQLite en modo de solo lectura y conserva el avance
aunque haya cambiado el código. No abre una cola nueva, autoriza, reencola,
valida vectores ni llama al modelo. La verificación completa sigue siendo
obligatoria antes de ejecutar o reanudar.

```powershell
uv run python run.py status --autonomous --run-id RUN_ID
uv run python run.py status --autonomous --run-id RUN_ID --json
```

El porcentaje es PASS dividido por trabajos proyecto–indicador declarados.
Los resultados parciales y los errores no representan proyectos completos.
Los proyectos sin trabajos LLM se informan aparte: el descubrimiento puede no
admitir candidatos, o puede faltar texto. No se presentan como evaluados por Qwen.
Un PID solo se considera activo cuando coincide también su identidad de creación.
Un checkpoint RUNNING abandonado se muestra interrumpido. El ETA solo aparece
con un worker activo, muestra suficiente y sin errores pendientes; es orientativo.
Las métricas ausentes no se sustituyen por cero. Durante una espera de RAM se
muestran la observación disponible, el umbral y el siguiente intervalo de revisión.

## Ejecuciones nuevas

`prepare --autonomous` conserva el adaptador individual por defecto.
`--batch-size 2` o `3` activa lotes explícitamente; `1` mantiene la evaluación
individual anterior. El lote, los prompts,
las fuentes y el código quedan sellados en el manifiesto. Se requieren permisos
explícitos del manifiesto antes de la inferencia, como en el flujo anterior.

- Se agrupan indicadores del mismo proyecto con fragmentos recuperados comunes.
- Se deduplican fragmentos idénticos, no sus asociaciones con cada indicador.
- Cada indicador conserva íntegros su catálogo, rúbrica, criterios, temporalidad,
  referencias permitidas y validación de evidencia/confianza.
- El esquema JSON comparte definiciones repetidas mediante `$defs`; se valida
  además cada respuesta contra el contrato individual más estricto.
- El contexto permanece estable en el mayor nivel autorizado de hasta 6144.
  Entrada real tokenizada, salida reservada y margen deben caber juntos. El
  esquema se registra como gramática externa de decodificación, sin contarlo
  otra vez como texto del prompt. No se elimina
  evidencia para admitir un lote. Si no cabe, se usa un lote menor o evaluación
  individual; si tampoco cabe, se registra el bloqueo y nunca un falso negativo.
- Los miembros válidos se guardan por separado antes del siguiente trabajo.
  Solo los inválidos reciben una aclaración individual pertinente, reutilizando
  su primera respuesta. No se repite el análisis inicial ni se vuelve a agrupar
  el miembro inválido. Los casos que no admiten agrupación usan el adaptador
  individual. Una llamada incierta conserva
  el plan y bloquea sus miembros; no se repite automáticamente al reanudar.
- Los fragmentos y candidatos parseados se reutilizan dentro del proyecto.
  La selección de fuentes sigue comprobándose; los embeddings válidos siguen
  usando las cachés del pipeline existente.
- Se cuenta una llamada física y sus tokens una sola vez por proyecto. En la
  cola, el indicador propietario recibe el 100% del uso compartido y los demás
  cero uso adicional. `batch_receipts/`, `batch_plans/` y `shared_call` en los
  resultados explican los miembros y la atribución. Los tres entregables no
  cambian su esquema.

Los lotes requieren un worker para impedir carreras de reserva. El modo anterior
con dos workers permanece disponible con `--batch-size 1`. El perfil opcional
`config/autonomous_optimized.json` revisa la RAM cada 30–60 segundos, manteniendo
el umbral de seguridad y las dos muestras estables. No reduce el requisito de RAM
ni cambia pesos, modelo, catálogo o confianza.

## Checkpoints

Para los lotes es necesario preparar también el tokenizador fijado, usando las
dependencias existentes. No descarga pesos ni ejecuta inferencia:

```powershell
uv run python scripts/prepare_qwen_tokenizer.py
```

Su revisión, SHA-256 y compatibilidad con el digest y la plantilla local están
en `config/qwen_tokenizer.json`. Se contrastó sin inferencias con 798 solicitudes
históricas: tokenizador más 12 tokens de plantilla coincide con todos los conteos
de entrada observados. El margen reservado es de 300 tokens, además de esos 12,
y la salida se adapta al número de criterios y al espacio disponible. El servidor
sigue verificándose antes/después de cada llamada y los conteos reales se
comprueban al recibirla; no hay truncamiento ni cambio automático de modelo.
La calibración corresponde a este digest/plantilla, no a cualquier instalación
de Qwen. Si cambian, la ejecución exige revisar la calibración.

Ollama recibe el esquema mediante `format`, separado de `messages`; véanse
[salidas estructuradas](https://ollama.com/blog/structured-outputs) y el
[contrato HTTP oficial](https://github.com/ollama/ollama/blob/main/docs/api.md).

Los resultados y transportes completos se adoptan sin volver a inferir. Ctrl+C
conserva resultados, planes, recibos y cola. Una respuesta cortada o incierta no
se transforma en una evaluación negativa. Tras comprobar que ya terminó la
llamada incierta, la recuperación explícita sigue disponible mediante
`retry-pending --acknowledge-uncertain`; puede implicar repetir una llamada cuyo
resultado nunca se recibió. Los bloqueos semánticos requieren revisión.

```powershell
uv run python run.py resume --autonomous --run-id RUN_ID
```

Los manifiestos históricos fijan el código anterior. **Se pueden monitorear con
esta versión, pero su reanudación requiere su versión autorizada**. No se actualizan
sus hashes ni se convierten silenciosamente a lotes. Reutilizar el manifiesto de
selección en un run nuevo conserva la muestra; no importa automáticamente sus
resultados de inferencia. La comparación pequeña exige inferir nuevamente el
proyecto elegido para medir la estrategia nueva.

## Preparar posteriormente los 100 seleccionados

Estos comandos son para ejecución posterior del usuario; no forman parte de la
prueba pequeña. Utilizar un `run_id` que aún no exista:

```powershell
$runId = 'muestra100_lotes_20261108_v1'
uv run python scripts/prepare_qwen_tokenizer.py
uv run python run.py prepare --autonomous --selection-manifest outputs/runs/run_20261108_154514_059252/preprocess/selection_manifest.json --policy config/autonomous_optimized.json --batch-size 2 --run-id $runId
$manifestPath = "outputs/runs/$runId/autonomous/main/manifest.json"
# Revisar el manifiesto antes de autorizar:
$manifestHash = (Get-FileHash -Algorithm SHA256 -LiteralPath $manifestPath).Hash.ToLowerInvariant()
uv run python run.py authorize --autonomous --run-id $runId --manifest-sha256 $manifestHash
uv run python run.py start --autonomous --run-id $runId
```

Desde otra terminal, usar los comandos `status` y `resume` anteriores con el
mismo ID. La terminal principal informa periódicamente el avance sin volcar IDs
masivos, evidencia ni respuestas completas.

## Diagnóstico histórico reproducible

```powershell
uv run python scripts/analyze_run_performance.py outputs/runs/run_20261108_154514_059252 --output docs/status/optimization_baseline_20261108.json
```

El script escribe fuera del run fuente y no ejecuta inferencias. Incluye llamadas
y tokens por solicitud, proyecto e indicador; errores, contextos, tiempos Ollama,
esperas de RAM, huecos entre solicitudes y performance original. Los tiempos de
Ollama forman parte de la inferencia y no deben sumarse otra vez al total.
