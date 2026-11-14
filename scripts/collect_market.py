"""Independent public ESPN pregame observations. Never imported by build_data."""
import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from build_data import json_bytes, normalize_team, write_if_changed

SCOREBOARD = 'https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard'
CORE = 'https://sports.core.api.espn.com/v2/sports/football/leagues/nfl/events/{id}/competitions/{id}/odds?limit=100'


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00')).astimezone(timezone.utc)


def kickoff(game):
    if not game.get('gametime'):
        return None
    return datetime.fromisoformat(f"{game['gameday']}T{game['gametime']}").replace(
        tzinfo=ZoneInfo('America/New_York')).astimezone(timezone.utc)


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def implied(value):
    n = number(value)
    if n is None or abs(n) < 100:
        return None
    return 100 / (n + 100) if n > 0 else -n / (100 - n)


def parse_book(odds):
    provider = odds.get('provider') or {}
    if not provider.get('id') or not provider.get('name'):
        return None
    home, away = odds.get('homeTeamOdds') or {}, odds.get('awayTeamOdds') or {}
    hm, am = number(home.get('moneyLine')), number(away.get('moneyLine'))
    hp, ap = implied(hm), implied(am)
    # A two-sided moneyline is required; never derive a probability from a spread.
    if hp is None or ap is None:
        return None
    spread = number(odds.get('spread'))
    hs = None
    if spread == 0:
        hs = 0.0
    elif spread is not None and home.get('favorite') is True:
        hs = -abs(spread)
    elif spread is not None and away.get('favorite') is True:
        hs = abs(spread)
    return dict(sportsbook_id=str(provider['id']), sportsbook=provider['name'],
                home_moneyline=hm, away_moneyline=am, home_probability=hp/(hp+ap),
                away_probability=ap/(hp+ap), home_spread=hs)


def observation(game, event, odds, now, source):
    competitions = event.get('competitions') or []
    if len(competitions) != 1 or str(event.get('id')) != str(game.get('espn')):
        raise ValueError('Unmatched ESPN game identity')
    comp = competitions[0]
    teams = {c['homeAway']: normalize_team(c['team']['abbreviation']) for c in comp['competitors']}
    if teams != {'home': game['home_team'], 'away': game['away_team']}:
        raise ValueError('ESPN team identity mismatch')
    start = instant(comp.get('date') or event['date'])
    state = (comp.get('status') or event.get('status') or {}).get('type', {}).get('state')
    if state != 'pre' or start <= now:
        return None
    # Deduplicate providers so one book never becomes a consensus.
    books = {}
    for item in odds:
        book = parse_book(item)
        if book:
            books[book['sportsbook_id']] = book
    if not books:
        return None
    books = sorted(books.values(), key=lambda b: b['sportsbook_id'])
    hp = sum(b['home_probability'] for b in books)/len(books)
    spreads = [b['home_spread'] for b in books if b['home_spread'] is not None]
    return dict(game_id=game['game_id'], espn_event_id=str(event['id']), season=game['season'],
                week=game['week'], home_team=game['home_team'], away_team=game['away_team'],
                kickoff=start.isoformat(), observed_at=now.isoformat(),
                market_favorite=game['home_team'] if hp > .5 else game['away_team'] if hp < .5 else None,
                home_probability=hp, away_probability=1-hp,
                home_spread=sum(spreads)/len(spreads) if spreads else None,
                spread_sportsbook_count=len(spreads), sportsbook_count=len(books),
                market_type='consensus' if len(books)>1 else 'single_sportsbook',
                sportsbooks=books, source='ESPN', source_url=source)


def save(root, rows, now):
    # Immutable full observations, including unchanged prices at each polling time.
    history = root / 'snapshots' / (now.strftime('%Y%m%dT%H%M%S%fZ') + '.json')
    write_if_changed(history, json_bytes({'schema_version': 1, 'observations': rows}))
    old_path = root / 'latest.json'
    previous = json.loads(old_path.read_text())['observations'] if old_path.exists() else []
    latest = {r['game_id']: r for r in previous}
    for row in rows:
        latest[row['game_id']] = row
    # Last successfully observed pregame quote, retained after kickoff or outages.
    write_if_changed(old_path, json_bytes({'schema_version': 1, 'observations': sorted(latest.values(), key=lambda r:r['game_id'])}))


def collect(season, docs, now=None):
    now = now or datetime.now(timezone.utc)
    games = json.loads((docs / 'seasons' / str(season) / 'schedule.json').read_text())['games']
    eligible = {str(g['espn']):g for g in games if g.get('espn') and g.get('status') != 'final'
                and (kickoff(g) is None or now < kickoff(g) < now + timedelta(days=15))}
    session = requests.Session()
    session.mount('https://', HTTPAdapter(max_retries=Retry(total=2, backoff_factor=1, status_forcelist=[500,502,503,504])))
    def get(url):
        response = session.get(url, timeout=(5, 15))
        response.raise_for_status()
        return response.json()
    rows, errors = [], []
    url = SCOREBOARD + '?dates=' + now.strftime('%Y%m%d') + '-' + (now+timedelta(days=14)).strftime('%Y%m%d') + '&limit=1000'
    try:
        events = get(url)['events']
        if not isinstance(events, list):
            raise ValueError('Invalid scoreboard events')
        for event in events:
            game = eligible.get(str(event.get('id')))
            if not game:
                continue
            try:
                comp = event['competitions'][0]
                start = instant(comp.get('date') or event['date'])
                if start <= now or (comp.get('status') or event.get('status') or {}).get('type', {}).get('state') != 'pre':
                    continue
                source = CORE.format(id=event['id'])
                try:
                    payload = get(source)
                    items = payload['items']
                    # Core collections can contain public resource references.
                    odds = [get(i['$ref'].replace('http://', 'https://', 1)) if '$ref' in i else i for i in items]
                except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
                    errors.append(f"{event['id']}: per-game odds unavailable: {exc}")
                    odds, source = comp.get('odds') or [], url
                if not odds:
                    odds, source = comp.get('odds') or [], url
                row = observation(game, event, odds, now, source)
                if row:
                    rows.append(row)
            except (ValueError, KeyError, TypeError, IndexError) as exc:
                errors.append(f"{event.get('id')}: {exc}")
    except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
        errors.append(f'Scoreboard unavailable: {exc}')
    root = docs / 'market' / str(season)
    if rows:
        save(root, rows, now)
    write_if_changed(root / 'status.json', json_bytes(dict(schema_version=1, attempted_at=now.isoformat(),
        observations_collected=len(rows), errors=errors, status='ok' if rows and not errors else 'partial' if rows else 'unavailable' if errors else 'no_available_odds')))
    print(f'Market: {len(rows)} pregame observations; {len(errors)} source errors')
    for error in errors:
        print(error, file=sys.stderr)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--season', type=int, required=True)
    parser.add_argument('--docs', type=Path, default=Path('docs'))
    args = parser.parse_args()
    collect(args.season, args.docs)
