"""Keep only freely redistributable sources in GitHub public shot cache."""
import json
from pathlib import Path
p=Path('data/shot_history.json')
if p.exists():
    rows=json.loads(p.read_text(encoding='utf8'))
    safe=[x for x in rows if x.get('source') == 'StatsBomb Open Data']
    p.write_text(json.dumps(safe,ensure_ascii=False,indent=2), encoding='utf8')
    print(f'Public cache kept {len(safe)} StatsBomb matches; excluded {len(rows)-len(safe)} other-source rows')
