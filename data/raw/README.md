# Fuentes originales inmutables

Este directorio representa archivos originales depositados explícitamente por su custodio.
El pipeline solo abre las fuentes para lectura. No copia automáticamente archivos externos,
no corrige CSV in-place y verifica SHA-256 antes y después de procesar.

La configuración local predeterminada lee las rutas institucionales externas indicadas en
config/sources.yaml. Se puede apuntar a data/raw sin cambiar código. Los archivos reales,
staging, canonical, outputs y documentos personales no se versionan.

Las fuentes sintéticas de data/samples/synthetic son públicas y ficticias. Nunca sustituir
una fuente institucional ausente por una muestra de manera silenciosa.

