"""Explicit maintenance download; ordinary exports use only the pinned local CSVs."""
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import requests

BASE = 'https://portalgis.dane.gov.co/mparcgis/rest/services/Divipola/Serv_DIVIPOLA_MGN_2025/FeatureServer'
DESTINATION = Path(__file__).resolve().parents[1] / 'resources/divipola'
LAYERS = {'departments': (319, 'DPTO_CCDGO,DPTO_CNMBRE'),
          'municipalities': (317, 'DPTO_CCDGO,MPIO_CDPMP,MPIO_CNMBRE,MPIO_TIPO,DPTO_CNMBRE'),
          'settlements': (305, 'DPTO_CCDGO,MPIO_CDPMP,ZU_CDIVI,ZU_CNMBRE,CLAS_CCDGO')}


def download():
    DESTINATION.mkdir(parents=True, exist_ok=True)
    manifest = dict(version='DIVIPOLA_MGN_2025', source=BASE,
                    retrieved_at=datetime.now(timezone.utc).isoformat(), files={})
    for name, (layer, fields) in LAYERS.items():
        url = f'{BASE}/{layer}/query'
        def query(**parameters):
            response = requests.get(url, params=dict(f='json', where='1=1', **parameters), timeout=90)
            response.raise_for_status()
            data = response.json()
            if 'error' in data:
                raise ValueError(data['error'])
            return data
        expected = query(returnCountOnly='true')['count']
        ids = sorted(query(returnIdsOnly='true')['objectIds'])
        if len(set(ids)) != expected:
            raise ValueError('Official object count mismatch')
        rows = []
        for offset in range(0, len(ids), 500):
            page = query(outFields=fields, returnGeometry='false',
                         objectIds=','.join(map(str, ids[offset:offset+500])))['features']
            if not page:
                raise ValueError('Incomplete official catalogue: ' + name)
            rows.extend(f['attributes'] for f in page)
        if len(rows) != expected or query(returnCountOnly='true')['count'] != expected:
            raise ValueError('Catalogue changed during download')
        path = DESTINATION / (name + '.csv')
        with path.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fields.split(','))
            writer.writeheader()
            writer.writerows(rows)
        manifest['files'][path.name] = dict(rows=len(rows), sha256=sha256(path.read_bytes()).hexdigest(),
                                            source_url=url, fields=fields)
        print(name, len(rows))
    (DESTINATION/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    download()
