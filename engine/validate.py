"""Block accidental publication of results-only or fabricated XGQ predictions."""
import json
import math
from .collect import OUTPUT

def validate(snapshot):
    if snapshot.get('schema_version') != 1:
        raise ValueError('Unexpected snapshot version')
    rows=snapshot.get('forecasts', [])
    if not isinstance(rows,list) or snapshot['coverage']['xgq_forecasts'] != len(rows):
        raise ValueError('Invalid forecast counts')
    ids=set()
    for p in rows:
        if p['source_basis'] != 'verified_shot_level_xg':
            raise ValueError('Unsupported model input')
        if p['id'] in ids: raise ValueError('Duplicate identity')
        ids.add(p['id'])
        if p['date'] < snapshot['as_of']:
            raise ValueError('Forecast is in the past')
        q=p['probabilities']
        probs=[q[k] for k in ('home','draw','away')]
        if any(not isinstance(n,(int,float)) or not math.isfinite(n) or n<0 or n>1 for n in probs):
            raise ValueError('Invalid probability')
        if abs(sum(probs)-1)>.00005:
            raise ValueError('Probabilities are not normalized')
        if p['history_home']<5 or p['history_away']<5:
            raise ValueError('Insufficient team shot history')
    return len(rows)

if __name__ == '__main__':
    s=json.loads((OUTPUT/'snapshot.json').read_text(encoding='utf8'))
    print('Validated',validate(s),'real XGQ-based predictions')
