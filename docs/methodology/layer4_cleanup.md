# Limpieza verificable de Capa 4

La limpieza usa el entrypoint `scripts/cleanup_layer4.py`. No altera algoritmos de
Capas 1–3 o 4B, fingerprints ni hashes esperados. Los resultados reales, la revisión
humana vigente, los manifests y los XML de aceptación se conservan. Una carpeta
vacía de pruebas puede retirarse; una publicación referenciada no es desechable
por su antigüedad.

El inventario privado `outputs/layer4/auditoria/cierre_v2/cleanup/inventory.json` identifica
propósito, fechas reales de archivos, versiones observadas en manifests, número
de archivos, tamaño y consumidores. Las fechas de modificación no se presentan
como fecha de evaluación. El inventario ampliado incorpora subdirectorios
temporales exactos sin convertir los informes de sus directorios padres en
material prescindible.

El escáner revisa código, configuración, tests, documentación y archivos de texto
de outputs/layer4. Distingue referencias documentales de consumidores de ejecución
o integridad. Las referencias desde el propio directorio temporal no se consideran
consumidores externos. Un archivo ilegible, un consumidor externo de código o
manifest, o un enlace/junction ajeno al caso permitido bloquea la eliminación. Nunca se
elimina un directorio no incluido expresamente en la allowlist del módulo.

Única excepción de enlaces: los alias de directorio SymbolicLink `*current` que
crea pytest, cuyo destino resuelto permanece dentro del MISMO target exacto.
No se siguen al inventariar ni respaldar; el journal conserva su ruta, destino
original y clase. Se revalidan antes de borrar y se restauran como alias después
de recuperar los bytes. Junctions y enlaces a destinos externos siguen bloqueados.

```powershell
.\.venv\Scripts\python.exe -B scripts/cleanup_layer4.py inventory --output outputs/layer4/auditoria/cierre_v2/cleanup/inventory_expanded.json
.\.venv\Scripts\python.exe -B scripts/cleanup_layer4.py plan --inventory outputs/layer4/auditoria/cierre_v2/cleanup/inventory_expanded.json --directory outputs/layer4/preliminary_tests --output outputs/layer4/auditoria/cierre_v2/cleanup/dry_run.json
```

Antes de `apply` se inspecciona el inventario y el dry-run. El script repite la
búsqueda de dependencias y compara todos los bytes actuales con el plan. Conserva
un ZIP privado que contiene únicamente lo seleccionado para borrar, comprueba
CRC, lista de miembros y SHA-256 de cada archivo y registra un journal antes de
la primera eliminación. Los vectores y publicaciones protegidas no se copian a
este respaldo cuando no forman parte de la operación. Toda ruta recursiva se
resuelve y contrasta con la allowlist dentro de outputs/layer4 antes de mutar.

```powershell
.\.venv\Scripts\python.exe -B scripts/cleanup_layer4.py apply --plan outputs/layer4/auditoria/cierre_v2/cleanup/dry_run.json --backup archives/layer4/cleanup_recovery_20261024.zip --journal outputs/layer4/auditoria/cierre_v2/cleanup/deletion_journal.json
```

El ZIP no es una nueva salida activa ni un archivo completo de todos los
experimentos: es recuperación puntual de la operación destructiva. El journal
explica exactamente qué se retiró, por qué y cómo verificar el respaldo. Un
journal parcial exige inspección; no se vuelve a ejecutar una eliminación con un
plan desactualizado ni se cambian sus hashes para aceptarlo.

```powershell
.\.venv\Scripts\python.exe -B scripts/cleanup_layer4.py restore --journal outputs/layer4/auditoria/cierre_v2/cleanup/deletion_journal.json
```

La recuperación verifica el ZIP y las rutas contra el journal y reconstruye
únicamente los archivos faltantes; rechaza sobrescribir bytes actuales distintos.
Los directorios vacíos se restauran desde la lista de targets del journal.

El run `experiment_closure20_v2_final` conserva sus rutas originales porque forman
parte de la preparación, de las autorizaciones y de referencias reproducibles.
Los originales históricos aceptados tampoco se mueven para mejorar visualmente
el árbol. `pruebas/` presenta exclusivamente el trabajo reciente vigente; las
obligaciones privadas de conservación permanecen identificadas por el inventario.

La única publicación de Capa 5 es `outputs/layer4/final/resultado_capa4.xlsx`.
El procedimiento activo debe exigir ejecución completa y aceptación humana y
usar `final_export.py`; ni la limpieza ni una exportación parcial la aprueban.
Contiene siete columnas de indicadores y cuatro columnas territoriales, sin
umbral de confianza ni métricas de desempeño. Los informes privados continúan en
`outputs/layer4/performance/`.
