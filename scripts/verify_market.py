"""Check generated market files and their actual public raw/Pages URLs."""
import argparse
import json
import time
from pathlib import Path

import requests


def validate(root):
    latest = json.loads((root / 'latest.json').read_text())
    status = json.loads((root / 'status.json').read_text())
    rows = latest['observations']
    fresh = [r for r in rows if r['observed_at'] == status['attempted_at']]
    assert len(fresh) == status['observations_collected'], 'Fresh count mismatch'
    for row in rows:
        assert 0 < row['home_probability'] < 1
        assert abs(row['home_probability'] + row['away_probability'] - 1) < 1e-9
        assert row['sportsbook_count'] == len(row['sportsbooks']) > 0
        assert row['observed_at'] < row['kickoff'], 'Quote is not pregame'
    if fresh:
        batches = [json.loads(p.read_text())['observations'] for p in (root / 'snapshots').glob('*.json')]
        assert any(all(r in batch for r in fresh) for batch in batches), 'Snapshot missing'
    return len(fresh)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int, required=True)
    parser.add_argument('--repository', required=True)
    args = parser.parse_args()
    root = Path('docs/market') / str(args.season)
    count = validate(root)
    owner, repo = args.repository.split('/')
    bases = [f'https://raw.githubusercontent.com/{owner}/{repo}/main/docs',
             f'https://{owner}.github.io/{repo}']
    for base in bases:
        for name in ('latest.json', 'status.json'):
            expected = json.loads((root / name).read_text())
            url = f'{base}/market/{args.season}/{name}'
            for attempt in range(24):
                try:
                    response = requests.get(url, params={'verify': expected.get('attempted_at', time.time())}, timeout=20)
                    if response.status_code == 200 and response.json() == expected:
                        print(f'HTTP 200, exact generated content: {url}', flush=True)
                        break
                    detail = f'HTTP {response.status_code}, content not yet current'
                except (requests.RequestException, ValueError) as exc:
                    detail = str(exc)
                if attempt == 23:
                    raise RuntimeError(f'{url}: {detail}')
                time.sleep(10)
    print(f'Published and verified {count} fresh valid pregame observations', flush=True)


if __name__ == '__main__':
    main()
