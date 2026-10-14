# Fixtures ficticias

No contienen personas, documentos ni investigación reales. Incluyen dos proyectos aceptados,
un duplicado, un ID obligatorio faltante, una fecha imposible, dos artículos, identidades por
empleado/documento, dos homónimos sin evidencia y una persona sin identificadores.
Los CSV también incluyen una fila física vacía final para comprobar su auditoría.

Los indicadores SYN-* son exclusivamente de prueba; no representan el catálogo oficial.
Ejecutar desde la raíz: python scripts/run_layer1.py --config config/sources.synthetic.yaml.
Esta ejecución publica una instantánea sintética en canonical; ejecutar posteriormente
la configuración real para restaurar el conjunto institucional. Tests usan directorios aislados.

