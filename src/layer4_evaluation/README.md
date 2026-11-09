# Capa 5 — indicadores, evaluación y resultados

La documentación operativa y el estado actual están en
[outputs/layer4/README.md](../../outputs/layer4/README.md).

Codex CLI es la interfaz mediante la cual el sistema utiliza un LLM para realizar
la interpretación semántica. El modelo descubre relaciones entre proyectos y los
48 perfiles, interpreta criterios, vincula citas y evalúa evidencias. Python
prepara datos, coordina llamadas y reanudación, valida contratos y citas, calcula
`100 × (0.55S + 0.45K)` y consolida/exporta. Capa 4B resuelve territorios de forma
determinista y no depende de Codex CLI.

## Módulos actuales

- `indicators/global_discovery_v3_3.py`: selección semántica versionada, cero a seis
  priorizados, citas y diagnóstico de descartes.
- `indicators/assessment_v3.py`: contrato vigente, validación determinista y confianza.
- `indicators/consumer_v3_3.py`: proyección futura de seis columnas, solo VALID
  SUPPORTED priorizados, estados conservados en auditoría; no publica.
- `indicators/final_export.py`: exportación histórica V2 de siete columnas.
- `paths.py`: resolución explícita de la reorganización sin reescribir fingerprints.
- `territories/`: extracción/resolución territorial y publicación 4B aceptada.

El ejecutor controlado `scripts/run_layer4_pilot_discovery_v3_3.py` autoriza una
llamada independiente, sin retry ni assessments automáticos. PROJ_20456 ya terminó;
PROJ_21299 sigue pendiente. No usar el cierre histórico V2 para ejecutar V3.3.
Los helpers históricos permanecen como procedencia, no como comandos de reanudación
universal. Las propuestas COL-01/CUL-01 y compactación JSON no están activadas.
No se ha publicado V3.3 ni reconstruido otra capa.
