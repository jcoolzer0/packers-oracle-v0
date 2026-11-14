import copy
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import collect_market as m

NOW = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)
GAME = dict(game_id='2026_11_GB_LAR', espn=123, season=2026, week=11,
            home_team='LAR', away_team='GB', gameday='2026-11-15', gametime='16:25', status='scheduled')
EVENT = dict(id='123', date='2026-11-15T21:25Z', competitions=[dict(
    status={'type': {'state':'pre'}}, competitors=[
        dict(homeAway='home', team={'abbreviation':'LA'}),
        dict(homeAway='away', team={'abbreviation':'GB'})])])
ODDS = dict(provider={'id':'1', 'name':'Test book'}, spread=3.5,
            homeTeamOdds={'moneyLine':-150, 'favorite':True},
            awayTeamOdds={'moneyLine':130, 'favorite':False})


class MarketTests(unittest.TestCase):
    def row(self, odds=None, event=None):
        return m.observation(GAME, event or EVENT, odds if odds is not None else [ODDS], NOW, 'https://example.com')

    def test_vig_spread_single_and_duplicates(self):
        row = self.row([ODDS, ODDS])
        self.assertAlmostEqual(row['home_probability'], .6/(.6+100/230))
        self.assertAlmostEqual(row['home_probability']+row['away_probability'], 1)
        self.assertEqual(row['home_spread'], -3.5)
        self.assertEqual(row['market_favorite'], 'LAR')
        self.assertEqual(row['market_type'], 'single_sportsbook')

    def test_consensus_and_missing_odds(self):
        other = copy.deepcopy(ODDS)
        other['provider'] = {'id':'2', 'name':'Other book'}
        other['homeTeamOdds']['moneyLine'] = 130
        other['awayTeamOdds']['moneyLine'] = -150
        self.assertAlmostEqual(self.row([ODDS, other])['home_probability'], .5)
        self.assertEqual(self.row([ODDS, other])['market_type'], 'consensus')
        self.assertIsNone(self.row([]))
        other['homeTeamOdds']['moneyLine'] = float('nan')
        self.assertIsNone(m.parse_book(other))

    def test_identity_and_live_odds_rejected(self):
        event = copy.deepcopy(EVENT)
        event['id'] = '999'
        with self.assertRaises(ValueError):
            self.row(event=event)
        event = copy.deepcopy(EVENT)
        event['competitions'][0]['competitors'][0]['team']['abbreviation'] = 'LAC'
        with self.assertRaises(ValueError):
            self.row(event=event)
        event = copy.deepcopy(EVENT)
        event['competitions'][0]['status']['type']['state'] = 'in'
        self.assertIsNone(self.row(event=event))
        event = copy.deepcopy(EVENT)
        event['date'] = '2026-11-12T21:25Z'
        self.assertIsNone(self.row(event=event))

    def test_archive_and_latest_retention(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            row = self.row()
            m.save(root, [row], NOW)
            m.save(root, [], datetime(2026,11,16,tzinfo=timezone.utc))
            self.assertEqual(json.loads((root/'latest.json').read_text())['observations'], [row])
            self.assertEqual(len(list((root/'snapshots').glob('*.json'))), 2)

    def test_source_failure_keeps_previous_quote(self):
        with tempfile.TemporaryDirectory() as d:
            docs = Path(d)
            schedule = docs/'seasons/2026/schedule.json'
            schedule.parent.mkdir(parents=True)
            schedule.write_text(json.dumps({'games':[GAME]}))
            root = docs/'market/2026'
            m.save(root, [self.row()], NOW)
            before = (root/'latest.json').read_bytes()
            with patch.object(m.requests.Session, 'get', side_effect=m.requests.ConnectionError('offline')):
                m.collect(2026, docs, NOW)
            self.assertEqual((root/'latest.json').read_bytes(), before)
            self.assertEqual(json.loads((root/'status.json').read_text())['status'], 'unavailable')

    def test_collector_core_reference(self):
        with tempfile.TemporaryDirectory() as d:
            docs = Path(d)
            schedule = docs/'seasons/2026/schedule.json'
            schedule.parent.mkdir(parents=True)
            schedule.write_text(json.dumps({'games':[GAME]}))
            responses = [Mock(json=lambda: {'events':[EVENT]}), Mock(json=lambda: {'items':[{'$ref':'http://sports.core.api.espn.com/book'}]}), Mock(json=lambda: ODDS)]
            with patch.object(m.requests.Session, 'get', side_effect=responses):
                m.collect(2026, docs, NOW)
            data = json.loads((docs/'market/2026/latest.json').read_text())
            self.assertEqual(data['observations'][0]['game_id'], GAME['game_id'])


if __name__ == '__main__':
    unittest.main()
