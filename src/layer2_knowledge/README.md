# Capa 2 — READY

Integrada con el canonical real oficial; paquete publicado en data/knowledge/.
Trazabilidad e idempotencia verificadas. Capa 3: NOT IMPLEMENTED YET.

Ver [arquitectura](../../docs/architecture/layer2.md),
[contrato](../../docs/contracts/layer2_knowledge_contract.md) y
[chunking](../../docs/contracts/chunking_contract.md).

CLI: `python scripts/run_layer2.py --mode profile|validate|publish`.
Config aprobada para un hash específico de Capa 1; un snapshot nuevo exige revisión.
Tests: `python -m pytest tests/layer2 -q --basetemp=outputs/layer2/unit-temp`.
Aceptación real: activar LAYER2_REAL_INTEGRATION=1 y LAYER2_VERIFY_PUBLICATION=1.
Verificación publicada: `python scripts/verify_layer2.py`.
