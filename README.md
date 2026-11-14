# Packers Oracle raw NFL data

A Python 3.12 collector for **2026 NFL regular-season** schedules, results and
team statistics. Predictive modeling belongs in Oracle Lens. No scraping or
prediction calculations are performed here.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r scripts/requirements.txt
.venv/bin/python -m unittest discover -s scripts/tests -v
.venv/bin/python scripts/build_data.py --season 2026
python3 -m http.server 8000 --directory docs
```

## Verified upstream feeds

- Schedule/results: https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv
- Weekly statistics: https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_week_2026.csv
- Regular-season totals: https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_reg_2026.csv
- Field definitions: https://nflreadr.nflverse.com/articles/dictionary_team_stats.html

Season is parameterized in both statistic URLs. All upstream schedule and team
statistic columns are retained, including newly added columns. Passing, rushing,
receiving, defensive tackles/sacks/interceptions, turnovers, penalties and
special-teams fields are included. Existing upstream EPA/CPOE fields are retained
as source data; the collector does not compute predictions. Unknown numeric
fields are parsed as numbers, empty values as JSON null, list fields as arrays
when valid JSON. Local TLS verification remains enabled.

## Lens contract (schema version 2)

`docs/seasons/2026/` is the authoritative season bundle. Root `docs/` JSON files
mirror the selected active season for compatibility with existing fetch paths.

| File | Contents |
| --- | --- |
| `teams.json` | All 32 canonical codes, lowercase file keys, full names |
| `schedule.json` | All 272 REG games, source columns, normalized identifiers, status |
| `team_stats.json` | `teams`: season totals; `weekly`: per-team/per-game source statistics |
| `<team>.json` | Existing `summary` and `games` layout, raw `statistics`, basic `defense_allowed` |
| `data.json` | Current-season raw schedule/statistics bundle |
| `manifest.json` | Source URLs/hashes, collection time, coverage, availability and quality flags |

Canonical codes are `LAR` (Rams), `LAC` (Chargers), `WSH` (Commanders), `GB`,
`JAX`, `LV` and the standard remaining abbreviations. LA/WAS and other known
source variations, full team names and historic relocation codes normalize
before joins. Ambiguous city-only names such as Los Angeles and New York are
rejected. Routine successful mappings produce no warnings. `la.json`, `LA.json`
and `was.json` remain copies for older clients.

`game_id` is normalized (`2026_01_LAR_WSH`); `source_game_id` preserves the
upstream identifier. Season/week/team/opponent joins are validated. `gameday`
and `gametime` retain upstream values (the feed's gametime is Eastern Time);
null times mean not yet assigned. Results become `final` only when both scores
are present; upcoming points/statistics are null, never invented zeroes.

Each team game retains `week`, `opponent`, `result` (W/L/T/null) and `score`
(team-relative `points_for-points_against`). It adds identifiers, venue side,
raw team `statistics` and `opponent_statistics`. Season summaries retain record
and win percentage; add games played and points for/against. `defense_allowed`
sums opponent passing/rushing yards, touchdowns and first downs over explicitly
reported statistics coverage. It does not substitute these for source defensive
statistics. No `oracle`, calibration, confidence or coherence values are emitted
for 2026. Consumers must use manifest coverage and null checks.

Source updates need not arrive together. `quality.missing_game_statistics` and
`quality.statistics_coverage_mismatches` identify delayed statistics; partial
coverage is explicitly labeled. Before the first game, unpublished statistic
feeds (404 only) produce `statistics_status: pending` and null team totals.
Missing all statistics after games have finished, failed network requests,
malformed schemas, duplicate games/statistics and unresolved teams fail the run
before writing output. Existing output is retained. Schedule validation requires
all 32 teams, 17 games each, 272 unique games and no double booking in a week.

## Historical preservation and repeatability

`docs/history/2025/` preserves **every original 2025 JSON file byte for byte**,
including its existing predictions and original data defects. This is an archive,
not newly validated source data. It is never touched by the collector.
Collect another season without replacing active-season files using:

```sh
.venv/bin/python scripts/build_data.py --season 2025 --no-publish-latest
```

This writes normalized raw data under `docs/seasons/2025/`, leaving the original
archive untouched. The collector supports the 17-game era (2021 onward). Source
responses use bounded retries, timeouts and ETag/Last-Modified conditional
requests. Cached content is hash-checked; failures do not silently reuse stale
responses. Identical source content produces identical JSON and retains
`collected_at`, so unchanged refreshes do not create duplicate commits. File
replacement is atomic; all source validation happens before publishing files.

## Automation

The GitHub Actions workflow supports manual refresh plus hourly collection on
potential game days (Sun/Mon/Thu/Fri/Sat) September–January, daily Tue/Wed refresh,
and weekly offseason refresh. It downloads only three feeds per run, uses a
conditional-response cache, serializes runs and commits only changed JSON.

Set repository variable `NFL_SEASON` to select the active season (default 2026).
When advancing seasons, set it after the complete new schedule is published;
older `docs/seasons/<year>/` bundles remain intact. Manual `season` overrides
collect a historical/future season without changing root files unless it matches
`NFL_SEASON`. Scheduled workflows run from the default branch; this update must
be reviewed and merged before the repaired automation is active. No tokens or
other API credentials are needed beyond Actions' standard contents-write token.

## Independent Vegas market reference (schema version 1)

`python scripts/collect_market.py --season 2026 --require-fresh` runs in the
independent `market.yml` workflow, even if the statistics source fails. No accounts, keys, or additional dependencies
are required. It queries ESPN's public NFL scoreboard by season, regular-season type and
week (`?dates=2026&seasontype=2&week=11&limit=100`) for event identity, kickoff
and pregame state, then the public per-game core odds collection for available
books (scoreboard odds are the fallback on a per-game source failure). ESPN's
undocumented endpoints can change; availability is never guaranteed. This
collector is never imported or consumed by the statistical collector or Oracle.
Historical files and existing statistical exports are unchanged.

- `docs/market/2026/latest.json`: `schema_version`, `observations` array; last
  successfully collected **pregame** observation for each canonical `game_id`.
- `docs/market/2026/snapshots/<UTC timestamp>.json`: immutable observation batches,
  including repeated prices at different polling times.
- `docs/market/2026/status.json`: most recent attempt time, count, status and errors.

Each observation includes `game_id`, `espn_event_id`, `season`, `week`,
`home_team`, `away_team`, UTC `kickoff`, `market_favorite` (null for a tie),
`home_probability`, `away_probability`, `home_spread` (negative favors home),
`source`, `source_url`, UTC `observed_at`, `market_type`, `sportsbook_count`,
`spread_sportsbook_count`, and `sportsbooks` with individual prices and normalized
probabilities. Probabilities are fractions: convert American moneylines to
implied probabilities, then divide each by their sum to remove bookmaker margin.
Consensus is the equal-weight mean of available unique books' normalized
probabilities and available home spreads; one book is `single_sportsbook`.
No moneyline pair means no probability observation. No reported spread means null.

Only matching ESPN IDs **and** canonical home/away teams are accepted. Only games
explicitly marked pregame with a future ESPN kickoff can produce observations;
no live or postgame odds are captured as pregame. Polling covers the next 14 days.
`latest.json` retains the last successful pregame quote after kickoff, including
through outages. This is a last-observed reference, not a guaranteed closing
line; compare its timestamp to kickoff. An outage or missing odds never erases
prior observations or substitutes historical nflverse prices as current odds.
Consult `status.json` and observation age before comparisons. The existing
hourly/daily in-season and weekly offseason schedules are retained. Collection
failures do not fail the statistics job. A market run fails visibly if upcoming
games exist but no fresh observations are collected; status and prior quotes
are still published. On an initial outage, latest.json contains an empty array
so consumers receive JSON rather than a missing resource.

The market workflow runs on the same schedule as statistics, on manual dispatch,
and when its collector or workflow changes on main. It commits only docs/market,
then validates both the raw and Pages URLs against the exact generated JSON.
The two workflows share a concurrency group to prevent commit races.

Published consumer URLs (no docs prefix for Pages):
- https://jcoolzer0.github.io/packers-oracle-v0/market/2026/latest.json
- https://raw.githubusercontent.com/jcoolzer0/packers-oracle-v0/main/docs/market/2026/latest.json

Run `python scripts/verify_market.py --season 2026 --repository
jcoolzer0/packers-oracle-v0` to validate probabilities, pregame times, snapshots,
fresh counts and both published URLs.
