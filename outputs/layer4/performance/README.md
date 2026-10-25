# Tiempo y recursos

`historico_cierre/` centraliza los reportes de desempeño del cierre V2, incluidos
sus manifiestos. No se copian aquí las respuestas ni los archivos nativos de llamadas.
Las métricas V3/V3.3 permanecen junto a sus intentos para mantener procedencia:

- `../pruebas/validacion_v3_3/control_positivo_v3_3_PROJ_20022.metrics.json`.
- `../pruebas/validacion_v3_3/prueba_controlada_v3_3_PROJ_22027/`.
- `../pruebas/validacion_v3_3/cierre_piloto_v3_3_PROJ_20899.runtime.json`.
- `../pruebas/validacion_v3_3/cierre_homogeneo_v3_3/PROJ_20456/verification.json`.
- `../pruebas/validacion_v3_3/preparacion_cierre_v3_3.consumo.json` (estimaciones y presupuestos).

PROJ_20456 consumió 49.786 tokens de entrada y 6.144 de salida: total 55.930;
120,438876 segundos, una llamada y cero reintentos. La reorganización no realizó
llamadas nuevas. Los presupuestos no son consumos medidos. CPU/RAM del proceso
Python son recursos locales; no describen GPU, CPU ni memoria remota del LLM.
