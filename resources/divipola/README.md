# DIVIPOLA local

Esta referencia ya instalada es **secundaria** para el CSV de indicadores. La autoridad de todos los códigos exportados y sus padres es `data/layer1_sources/reference/Codigos Dane/Tabla_Codigos_Dane.xlsx`. El exportador reutiliza aquí únicamente variantes verificables de nombres y relaciones de centros poblados cuyos municipios/padres estén presentes en ese Excel. No descarga ni actualiza este directorio durante las ejecuciones.

Copia pública de las tablas oficiales del DANE, servicio **DIVIPOLA MGN 2025**:

https://portalgis.dane.gov.co/mparcgis/rest/services/Divipola/Serv_DIVIPOLA_MGN_2025/FeatureServer

Referencia institucional:
https://www.dane.gov.co/index.php/sistema-estadistico-nacional-sen/normas-y-estandares/nomenclaturas-y-clasificaciones/nomenclaturas/codificacion-de-la-division-politica-administrativa-de-colombia-divipola

- `departments.csv`: capa 319, 33 registros (32 departamentos y Bogotá, D.C.).
- `municipalities.csv`: capa 317, 1.122 unidades de nivel municipal. Incluye 18 áreas no municipalizadas; estas no se presentan como municipios.
- `settlements.csv`: capa 305, 8.420 registros de cabeceras/centros poblados con sus códigos parentales. No constituye un inventario exhaustivo de veredas.
- `manifest.json`: fecha UTC de descarga, consultas, campos, conteos y SHA-256 de los archivos.

Su lectura opcional valida la integridad, sin red. La siguiente utilidad es de mantenimiento de esta referencia secundaria y no forma parte del flujo de resultados:

```powershell
.\.venv\Scripts\python.exe scripts/update_divipola_catalog.py
```

El descargador verifica los conteos de las capas, obtiene sus identificadores y descarga lotes de identificadores. No depende de paginación implícita ni del límite de respuesta del servidor. Los nombres y códigos CSV permanecen como los publica DANE; la presentación y los alias ortográficos se aplican únicamente al resolver.

Las veredas y otros lugares ausentes de DIVIPOLA requieren un vínculo explícito con un municipio dentro del mismo documento. Un nombre homónimo sin contexto suficiente no determina un municipio.
