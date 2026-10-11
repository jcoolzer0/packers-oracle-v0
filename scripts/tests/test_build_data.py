import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build_data as collector


def csv_text(rows):
    stream = io.StringIO()
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def fixtures():
    # 17 rounds of a 32-team round robin: every team plays exactly once a week.
    rotation = list(collector.TEAM_NAMES)
    schedule, weekly, totals = [], [], []
    source = lambda t: {'LAR': 'LA', 'WSH': 'WAS'}.get(t, t)
    for week in range(1, 18):
        for i in range(16):
            away, home = source(rotation[i]), source(rotation[-i-1])
            gid = f'2026_{week:02d}_{away}_{home}'
            schedule.append(dict(game_id=gid, season=2026, game_type='REG', week=week,
                                 gameday='2026-09-13', home_team=home, away_team=away,
                                 home_score=21 if week == 1 else '', away_score=21 if week == 1 else ''))
            if week == 1:
                for team, opponent in [(home, away), (away, home)]:
                    weekly.append(dict(season=2026, team=team, season_type='REG', week=week,
                                       game_id=gid, opponent_team=opponent, passing_yards=200,
                                       rushing_yards=100, def_sacks=2, def_interceptions=1,
                                       passing_tds=2, rushing_tds=1, new_source_metric=7,
                                       fg_made_list='[35, 40]'))
        rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
    for team in collector.TEAM_NAMES:
        totals.append(dict(season=2026, team=source(team), season_type='REG', games=1,
                           passing_yards=200, rushing_yards=100, def_sacks=2, def_interceptions=1))
    return schedule, weekly, totals


class FixtureFetcher:
    def __init__(self, schedule, weekly, totals):
        self.sources = []
        self.data = [csv_text(schedule), csv_text(weekly) if weekly else None, csv_text(totals) if totals else None]

    def get(self, url, optional=False):
        data = self.data.pop(0)
        self.sources.append({'url': url, 'status': 'available' if data else 'not_published',
                             'sha256': collector.hashlib.sha256(data.encode()).hexdigest() if data else None})
        return data


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.schedule, self.weekly, self.totals = fixtures()

    def games(self):
        return collector.normalize_schedule(csv_text(self.schedule), 2026)

    def test_aliases_and_ambiguous_names(self):
        for alias, expected in [('LA', 'LAR'), ('WAS', 'WSH'), ('GNB', 'GB'), ('JAC', 'JAX'),
                                ('Los Angeles Chargers', 'LAC'), ('Los Angeles Rams', 'LAR'),
                                ('New York Giants', 'NYG'), ('Oakland Raiders', 'LV')]:
            self.assertEqual(collector.normalize_team(alias), expected)
        for ambiguous in ['Los Angeles', 'New York', 'AFC', 'UNKNOWN']:
            with self.assertRaises(collector.DataError):
                collector.normalize_team(ambiguous)

    def test_complete_coverage_and_score_status(self):
        games = self.games()
        self.assertEqual(len(games), 272)
        self.assertEqual(sum(g['status'] == 'final' for g in games), 16)
        self.assertIn('LAR', {g['home_team'] for g in games} | {g['away_team'] for g in games})
        self.assertTrue(all('_LA_' not in g['game_id'] for g in games))
        self.assertTrue(any('_LA_' in g['source_game_id'] for g in games))
        self.assertIsNone(games[-1]['home_score'])

    def test_invalid_schedules_rejected(self):
        for mutation in ['missing', 'duplicate', 'partial_score', 'unknown', 'bad_date', 'negative_score']:
            rows = [dict(r) for r in self.schedule]
            if mutation == 'missing': rows.pop()
            if mutation == 'duplicate': rows[-1] = dict(rows[0])
            if mutation == 'partial_score': rows[0]['away_score'] = ''
            if mutation == 'unknown': rows[0]['home_team'] = 'LOS ANGELES'
            if mutation == 'bad_date': rows[0]['gameday'] = 'not-a-date'
            if mutation == 'negative_score': rows[0]['home_score'] = -1
            with self.subTest(mutation=mutation), self.assertRaises(collector.DataError):
                collector.normalize_schedule(csv_text(rows), 2026)

    def test_raw_fields_and_stats_joins(self):
        weekly = collector.normalize_stats(csv_text(self.weekly), 2026, 'week')
        totals = collector.normalize_stats(csv_text(self.totals), 2026, 'reg')
        self.assertEqual(weekly[0]['new_source_metric'], 7)
        self.assertEqual(weekly[0]['fg_made_list'], [35, 40])
        self.assertFalse(any(collector.validate_join(self.games(), weekly, totals).values()))
        weekly[0]['opponent_team'] = weekly[0]['team']
        with self.assertRaises(collector.DataError):
            collector.validate_join(self.games(), weekly, totals)

    def test_duplicate_and_malformed_statistics(self):
        rows = [*self.weekly, self.weekly[0]]
        with self.assertRaises(collector.DataError):
            collector.normalize_stats(csv_text(rows), 2026, 'week')
        rows = [dict(r) for r in self.weekly]
        rows[0]['passing_yards'] = 'NaN'
        with self.assertRaises(collector.DataError):
            collector.normalize_stats(csv_text(rows), 2026, 'week')
        with self.assertRaises(collector.DataError):
            collector.parse_csv('foo,bar\n1,2', {'season'})

    def test_nonfinite_values_rejected(self):
        for value in ['inf', '-inf', 'Infinity']:
            with self.subTest(value=value), self.assertRaises(collector.DataError):
                collector.scalar(value)

    def test_statistics_lag_is_explicit(self):
        weekly = collector.normalize_stats(csv_text(self.weekly[1:]), 2026, 'week')
        totals = collector.normalize_stats(csv_text(self.totals), 2026, 'reg')
        quality = collector.validate_join(self.games(), weekly, totals)
        self.assertEqual(len(quality['missing_game_statistics']), 1)
        self.assertTrue(quality['statistics_coverage_mismatches'])
        with self.assertRaises(collector.DataError):
            collector.validate_join(self.games(), [], [])

    def test_output_repeatability_history_and_team_games(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            history = root / 'history/2025/gb.json'
            history.parent.mkdir(parents=True)
            history.write_bytes(b'original historical data')
            run = lambda: collector.collect(2026, root, FixtureFetcher(self.schedule, self.weekly, self.totals))
            manifest = run()
            self.assertEqual(manifest['statistics_status'], 'available')
            before = {p.relative_to(root): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*.json')}
            run()
            after = {p.relative_to(root): (p.read_bytes(), p.stat().st_mtime_ns) for p in root.rglob('*.json')}
            self.assertEqual(before, after)
            self.assertEqual(history.read_bytes(), b'original historical data')
            rams = json.loads((root / 'lar.json').read_text())
            self.assertEqual(rams['summary']['record'], '0-0-1')
            self.assertEqual(rams['summary']['games_played'], 1)
            self.assertEqual(len(rams['games']), 17)
            self.assertEqual(rams['defense_allowed']['passing_yards_allowed'], 200)
            self.assertNotIn('oracle', rams['games'][0])
            self.assertEqual((root/'lar.json').read_bytes(), (root/'la.json').read_bytes())
            self.assertEqual((root/'wsh.json').read_bytes(), (root/'was.json').read_bytes())
            self.assertEqual((root/'lar.json').read_bytes(), (root/'seasons/2026/lar.json').read_bytes())
            self.assertEqual(rams['games'][1]['statistics'], None)

    def test_preseason_unpublished_stats_and_archive_only_mode(self):
        rows = [dict(r, home_score='', away_score='') for r in self.schedule]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'teams.json').write_bytes(b'existing active season')
            result = collector.collect(2026, root, FixtureFetcher(rows, [], []), publish_latest=False)
            self.assertEqual(result['statistics_status'], 'pending')
            self.assertEqual((root/'teams.json').read_bytes(), b'existing active season')
            team = json.loads((root/'seasons/2026/gb.json').read_text())
            self.assertIsNone(team['statistics'])
            self.assertIsNone(team['summary']['win_pct'])

    def test_failed_collection_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'teams.json').write_bytes(b'previous validated output')
            with self.assertRaises(collector.DataError):
                collector.collect(2026, root, FixtureFetcher(self.schedule[:-1], self.weekly, self.totals))
            self.assertEqual(list(root.iterdir()), [root/'teams.json'])
            self.assertEqual((root/'teams.json').read_bytes(), b'previous validated output')

    def test_http_cache_conditional_requests_and_failures(self):
        with tempfile.TemporaryDirectory() as temp:
            fetcher = collector.Fetcher(temp)
            response = Mock(status_code=200, content=b'csv content', headers={'ETag': 'abc'})
            response.raise_for_status.return_value = None
            fetcher.session.get = Mock(return_value=response)
            self.assertEqual(fetcher.get('https://example.com/feed'), 'csv content')
            fetcher.session.get.return_value = Mock(status_code=304)
            self.assertEqual(fetcher.get('https://example.com/feed'), 'csv content')
            self.assertEqual(fetcher.session.get.call_args.kwargs['headers'], {'If-None-Match': 'abc'})
            fetcher.session.get.side_effect = collector.requests.Timeout('unavailable')
            with self.assertRaises(collector.requests.Timeout):
                fetcher.get('https://example.com/feed')


if __name__ == '__main__':
    unittest.main()
