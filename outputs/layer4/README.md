# Capa 4: indicadores y territorios

La publicación vigente es **V2**, `final/resultado_capa4.xlsx`; no se ha publicado
V3.3. Su SHA-256 es
`fc6f876493ee327f140f5fbdbd234b93242eeaee15d86aa752388980f03332e1`.
Su manifiesto original está en `auditoria/cierre_v2/final_manifest.json`.

## Funcionamiento

Capa 1 prepara las fuentes; Capa 2 conserva documentos y secciones identificables;
Capa 3 proporciona candidatos GraphRAG. Capa 4A descubre y evalúa relaciones
PROJECT+INDICATOR. Capa 5 y Power BI consumen la publicación aprobada.

**Codex CLI es la interfaz mediante la cual el sistema utiliza un LLM para realizar
la interpretación semántica.** El modelo de lenguaje subyacente interpreta los
textos, examina los indicadores institucionales, descubre relaciones pertinentes,
vincula criterios con citas y evalúa su respaldo con explicaciones fundamentadas.
Python prepara datos, coordina llamadas y reanudación, valida contratos y citas
literales, calcula la confianza, consolida y prepara la exportación. Python no
reemplaza la selección semántica con palabras clave.

`GLOBAL_DISCOVERY_V3_3` examina los 48 perfiles habilitados. Puede priorizar de
cero a seis candidatos; seis es un máximo. Admite evidencia directa o parcial
específica, descarta similitud temática y especulación, y aplica la misma revisión
a GraphRAG. El backlog conservado no equivale a assessments realizados.
Cada assessment válido conserva SUPPORTED, INSUFFICIENT_EVIDENCE o NOT_SUPPORTED.
Se validan citas literales, identidad, criterios, temporalidad, contratos y hashes.
La confianza sigue siendo `100 × (0.55S + 0.45K)`; no es una probabilidad
estadística ni un umbral para seleccionar candidatos.

Capa 4B utiliza procesamiento territorial **determinista**, documentos de Capa 2
y el catálogo territorial aceptado. No depende de Codex CLI ni de Capa 3 para
resolver territorios. Se preservan códigos y reglas existentes.

## Estructura

| Ruta | Contenido |
|---|---|
| `final/` | Excel V2 oficial protegido; futura sustitución requiere aprobación. |
| `pruebas/piloto_v2/` | Piloto aceptado, cierre y evidencias de V2. |
| `pruebas/validacion_v3_3/` | Piloto V3 histórico, controles V3.3 y reanudación. |
| `performance/` | Reportes de recursos e índice de métricas nativas. |
| `territorios/` | Publicación, aceptación y versiones de Capa 4B. |
| `auditoria/` | Manifiestos, inventarios, limpieza, rutas y versiones históricas. |

Los JSON congelados mantienen las rutas originales y fingerprints. El registro
`auditoria/rutas.json` y `src/layer4/paths.py` resuelven sus ubicaciones nuevas.
Para código modificado por la migración se conservan bytes originales una sola
vez y se comprueba además el hash del código actual; esto documenta una migración,
no afirma que ambos códigos tengan el mismo hash. No editar manifiestos para
adaptarlos ni borrar registros de fallos.

La comprobación de inventarios se ejecuta con
`scripts/auxiliary/verify_layer4_layout.py --report outputs/layer4/auditoria/integrity_sandbox.json`.
Las restricciones de acceso de fixtures se distinguen de archivos ausentes o
hashes incorrectos; los informes complementarios y su cobertura combinada están
en `auditoria/recovery_completion.json`.

## Ejecución y verificación

Desde la raíz del repositorio, verificación sin inferencia del descubrimiento ya
completado:

```powershell
.\.venv\Scripts\python.exe -B scripts/run_layer4_pilot_discovery_v3_3.py verify --project PROJ_20456
```

La reanudación actual se describe en `auditoria/estado_reanudacion_v3_3.json` y
`pruebas/validacion_v3_3/README.md`. No ejecutar indiscriminadamente los helpers
históricos. Cada nueva llamada necesita autorización específica. El ejecutor
controlado permite una llamada, sin reintentos ni assessments automáticos.
Los planes y artefactos nativos conservan versiones de discovery, rúbrica,
assessment, prompts, comando, schemas, ejecución y consumo. No activar las
propuestas COL-01/CUL-01 ni la compactación experimental. Cuando el modelo
efectivo no figure en las métricas, no deducirlo de la interfaz CLI.

Pruebas locales de rutas, exportación y control de ejecución:

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests/layer4_experiment/test_layout_relocation.py tests/layer4_experiment/test_consumer_v3_3.py tests/layer4_experiment/test_pilot_single_discovery_control.py tests/layer4_experiment/test_final_territories.py -q -p no:cacheprovider
```

## Salida futura para Power BI

El contrato preparado `LAYER4_CONSUMER_V3_3_V1` contiene exactamente dos pestañas:

- RESULTADO_INDICADORES: `siap_id`, `indicador_id`, `parrafo_evidencia`,
  `fuente_evidencia`, `ubicacion_evidencia`, `confianza`.
- TERRITORIOS: `siap_id`, `territory_type`, `territory_code`, `code_system`.

Solo se exportarán relaciones priorizadas por V3.3 con assessment VALID y
SUPPORTED, citas verificadas y confianza validada. Las relaciones insuficientes,
negativas, inválidas o descartadas permanecen en auditoría; no se cambian sus
decisiones. Así la ausencia de una columna de estado no convierte evidencia
parcial en cumplimiento. El preparador es una proyección y un verificador:
no publica ni crea una nueva versión oficial. El Excel V2 conserva su contrato
anterior de siete columnas hasta aprobar su sustitución. Véanse los contratos en
`docs/contracts/layer4_output_contract.md` y `layer4_powerbi_contract.md`.
