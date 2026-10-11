"""Collect nflverse raw regular-season data; no predictive calculations.

Run: python scripts/build_data.py --season 2026
The public JSON contract is documented in README.md. Fail before publishing when
sources are malformed; a transport error must never turn into an empty season.
"""
import argparse
import csv
import hashlib
import io
import json
import math
import os
import re
import sys
import tempfile
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

SCHEDULE_URL = "https://raw.githubusercontent.com/nflverse/nfldata/master/data/games.csv"
STATS_URL = "https://github.com/nflverse/nflverse-data/releases/download/stats_team/stats_team_{level}_{season}.csv"
SCHEMA_VERSION = 2
TEAM_NAMES = {
    "ARI": "Arizona Cardinals", "ATL": "Atlanta Falcons", "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills", "CAR": "Carolina Panthers", "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals", "CLE": "Cleveland Browns", "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos", "DET": "Detroit Lions", "GB": "Green Bay Packers",
    "HOU": "Houston Texans", "IND": "Indianapolis Colts", "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs", "LAC": "Los Angeles Chargers", "LAR": "Los Angeles Rams",
    "LV": "Las Vegas Raiders", "MIA": "Miami Dolphins", "MIN": "Minnesota Vikings",
    "NE": "New England Patriots", "NO": "New Orleans Saints", "NYG": "New York Giants",
    "NYJ": "New York Jets", "PHI": "Philadelphia Eagles", "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks", "SF": "San Francisco 49ers", "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans", "WSH": "Washington Commanders",
}
ALIASES = {"LA": "LAR", "RAMS": "LAR", "WAS": "WSH", "WASHINGTON FOOTBALL TEAM": "WSH",
           "WASHINGTON REDSKINS": "WSH", "GNB": "GB", "KAN": "KC", "NWE": "NE",
           "NOR": "NO", "SFO": "SF", "TAM": "TB", "JAC": "JAX", "LACH": "LAC",
           "CHARGERS": "LAC", "OAK": "LV", "OAKLAND RAIDERS": "LV", "SD": "LAC",
           "SDG": "LAC", "SAN DIEGO CHARGERS": "LAC", "STL": "LAR", "ST. LOUIS RAMS": "LAR"}
ALIASES.update({name.upper(): team for team, name in TEAM_NAMES.items()})
OUTPUT_ALIASES = {"LAR": ["la", "LA"], "WSH": ["was"]}
NULL_VALUES = {"", "NA", "NaN", "nan", "null", "None"}


class DataError(ValueError):
    pass


def normalize_team(value):
    token = str(value).strip().upper()
    team = ALIASES.get(token, token)
    if team not in TEAM_NAMES:
        raise DataError(f"Unresolved team identifier: {value!r}")
    return team


def normalize_game_id(value):
    parts = str(value).split("_")
    if len(parts) != 4 or not parts[0].isdigit() or not parts[1].isdigit():
        raise DataError(f"Invalid game_id: {value!r}")
    return f"{int(parts[0])}_{int(parts[1]):02d}_{normalize_team(parts[2])}_{normalize_team(parts[3])}"


def scalar(value):
    if value in NULL_VALUES:
        return None
    if re.fullmatch(r"-?\d+", value):
        return int(value)
    try:
        number = float(value)
    except ValueError:
        if value.startswith("["):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass
        return value
    if not math.isfinite(number):
        raise DataError(f"Non-finite statistic: {value}")
    return number


def parse_csv(text, required):
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    if not required.issubset(reader.fieldnames or []):
        raise DataError(f"Missing CSV columns: {sorted(required - set(reader.fieldnames or []))}")
    rows = list(reader)
    if any(None in row or any(v is None for v in row.values()) for row in rows):
        raise DataError("Malformed CSV row")
    return rows


def integer(value, label, low=0, high=None):
    number = scalar(str(value))
    if not isinstance(number, int) or number < low or (high is not None and number > high):
        raise DataError(f"Invalid {label}: {value!r}")
    return number


def normalize_schedule(text, season):
    required = {"game_id", "season", "game_type", "week", "gameday", "home_team", "away_team", "home_score", "away_score"}
    rows = parse_csv(text, required)
    games = []
    for raw in rows:
        if raw["season"] != str(season) or raw["game_type"] != "REG":
            continue
        game = {k: scalar(v) for k, v in raw.items()}
        for key in ("home_team", "away_team"):
            game[key] = normalize_team(raw[key])
        game["source_game_id"] = raw["game_id"]
        game["game_id"] = normalize_game_id(raw["game_id"])
        game["week"] = integer(raw["week"], "week", 1, 18)
        expected_id = f"{season}_{game['week']:02d}_{game['away_team']}_{game['home_team']}"
        if game["game_id"] != expected_id or game["home_team"] == game["away_team"]:
            raise DataError(f"Game/team mismatch: {game['game_id']}")
        try:
            date.fromisoformat(raw["gameday"])
        except ValueError as exc:
            raise DataError(f"Invalid game date: {raw['gameday']}") from exc
        scores = [game["home_score"], game["away_score"]]
        if (scores[0] is None) != (scores[1] is None):
            raise DataError(f"Partial score: {game['game_id']}")
        for score in scores:
            if score is not None:
                integer(score, "score")
        game["status"] = "final" if scores[0] is not None else "scheduled"
        games.append(game)
    if len(games) != 272 or len({g["game_id"] for g in games}) != 272:
        raise DataError(f"Incomplete/duplicate {season} regular-season schedule: {len(games)} rows (expected 272)")
    counts = Counter(t for g in games for t in [g["home_team"], g["away_team"]])
    if set(counts) != set(TEAM_NAMES) or any(n != 17 for n in counts.values()):
        raise DataError(f"Invalid 32-team/17-game coverage: {dict(counts)}")
    slots = [(g["week"], t) for g in games for t in [g["home_team"], g["away_team"]]]
    if len(set(slots)) != len(slots):
        raise DataError("A team appears twice in one week")
    return sorted(games, key=lambda g: (g["week"], g["game_id"]))


def normalize_stats(text, season, level):
    required = {"season", "team", "season_type", "passing_yards", "rushing_yards", "def_sacks", "def_interceptions"}
    required |= {"week", "game_id", "opponent_team"} if level == "week" else {"games"}
    rows = []
    for raw in parse_csv(text, required):
        if raw["season"] != str(season) or raw["season_type"] != "REG":
            continue
        row = {k: scalar(v) for k, v in raw.items()}
        row["team"] = normalize_team(raw["team"])
        if level == "week":
            row["opponent_team"] = normalize_team(raw["opponent_team"])
            row["source_game_id"] = raw["game_id"]
            row["game_id"] = normalize_game_id(raw["game_id"])
            row["week"] = integer(raw["week"], "stats week", 1, 18)
        else:
            row["games"] = integer(raw["games"], "stats games", 0, 17)
        for field in required - {"team", "season_type", "game_id", "opponent_team"}:
            if not isinstance(row[field], (int, float)):
                raise DataError(f"Invalid numeric statistic {field} for {row['team']}")
        rows.append(row)
    keys = [(r["team"], r.get("game_id")) for r in rows]
    if len(set(keys)) != len(keys):
        raise DataError(f"Duplicate {level} team statistics")
    return sorted(rows, key=lambda r: (r.get("week", 0), r["team"]))


def validate_join(games, weekly, totals):
    by_id = {g["game_id"]: g for g in games}
    for row in weekly:
        game = by_id.get(row["game_id"])
        if not game or game["status"] != "final":
            raise DataError(f"Statistics reference an unknown/unplayed game: {row['game_id']}")
        home = row["team"] == game["home_team"]
        opponent = game["away_team"] if home else game["home_team"]
        if row["team"] not in (game["home_team"], game["away_team"]) or row["opponent_team"] != opponent or row["week"] != game["week"]:
            raise DataError(f"Statistics team/opponent/week mismatch: {row['game_id']} {row['team']}")
    completed = [g for g in games if g["status"] == "final"]
    if completed and (not weekly or not totals):
        raise DataError("Completed games exist but required team statistics are unavailable")
    present = {(r["game_id"], r["team"]) for r in weekly}
    missing = [{"game_id": g["game_id"], "team": t} for g in completed for t in [g["home_team"], g["away_team"]] if (g["game_id"], t) not in present]
    total_map = {r["team"]: r for r in totals}
    mismatches = []
    for team in TEAM_NAMES:
        n_weekly = sum(r["team"] == team for r in weekly)
        n_final = sum(team in (g["home_team"], g["away_team"]) for g in completed)
        total = total_map.get(team)
        if n_final and (not total or total["games"] != n_weekly or n_weekly != n_final):
            mismatches.append({"team": team, "schedule_games": n_final, "weekly_stat_games": n_weekly, "season_stat_games": total["games"] if total else None})
    return {"missing_game_statistics": missing, "statistics_coverage_mismatches": mismatches}


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def write_if_changed(path, content):
    if path.exists() and path.read_bytes() == content:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(content)
        tmp = handle.name
    os.replace(tmp, path)
    return True


class Fetcher:
    """Conditional HTTP downloads with bounded retries; never use stale data silently."""
    def __init__(self, cache_dir):
        self.cache_dir = Path(cache_dir)
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "PackersOracle/2 (nflverse raw data collector)"
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"])
        self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.sources = []

    def get(self, url, optional=False):
        key = hashlib.sha256(url.encode()).hexdigest()
        data_path = self.cache_dir / (key + ".csv")
        meta_path = self.cache_dir / (key + ".json")
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        headers = {}
        if data_path.exists() and hashlib.sha256(data_path.read_bytes()).hexdigest() == meta.get("sha256"):
            if meta.get("etag"):
                headers["If-None-Match"] = meta["etag"]
            if meta.get("last_modified"):
                headers["If-Modified-Since"] = meta["last_modified"]
        response = self.session.get(url, headers=headers, timeout=(15, 90))
        if response.status_code == 404 and optional:
            self.sources.append({"url": url, "status": "not_published", "sha256": None})
            return None
        if response.status_code == 304 and headers:
            content = data_path.read_bytes()
        else:
            response.raise_for_status()
            content = response.content
            write_if_changed(data_path, content)
            meta = {"etag": response.headers.get("ETag"), "last_modified": response.headers.get("Last-Modified"), "sha256": hashlib.sha256(content).hexdigest()}
            write_if_changed(meta_path, json_bytes(meta))
        self.sources.append({"url": url, "status": "available", "sha256": hashlib.sha256(content).hexdigest()})
        return content.decode("utf-8-sig")


def team_payload(team, season, games, weekly, totals):
    stats = {r["game_id"]: r for r in weekly if r["team"] == team}
    other_stats = {(r["game_id"], r["team"]): r for r in weekly}
    team_games = []
    wins = losses = ties = pf = pa = 0
    for game in games:
        if team not in (game["home_team"], game["away_team"]):
            continue
        home = game["home_team"] == team
        opponent = game["away_team"] if home else game["home_team"]
        scored = game["home_score"] if home else game["away_score"]
        allowed = game["away_score"] if home else game["home_score"]
        result = None
        if game["status"] == "final":
            result = "W" if scored > allowed else "L" if scored < allowed else "T"
            wins += result == "W"; losses += result == "L"; ties += result == "T"
            pf += scored; pa += allowed
        team_games.append({"game_id": game["game_id"], "source_game_id": game["source_game_id"], "week": game["week"],
                           "gameday": game["gameday"], "gametime": game.get("gametime"), "opponent": opponent,
                           "is_home": home, "status": game["status"], "result": result,
                           "score": f"{scored}-{allowed}" if result else None, "points_for": scored, "points_against": allowed,
                           "statistics": stats.get(game["game_id"]),
                           "opponent_statistics": other_stats.get((game["game_id"], opponent))})
    played = wins + losses + ties
    total = next((r for r in totals if r["team"] == team), None)
    # Opponent offense gives defensive allowed metrics; preserve partial coverage explicitly.
    defensive = {"games_with_opponent_statistics": sum(g["opponent_statistics"] is not None for g in team_games)}
    for field in ["passing_yards", "rushing_yards", "passing_tds", "rushing_tds", "passing_first_downs", "rushing_first_downs"]:
        values = [g["opponent_statistics"][field] for g in team_games if g["opponent_statistics"] is not None and g["opponent_statistics"].get(field) is not None]
        defensive[field + "_allowed"] = sum(values) if values else None
    return {"schema_version": SCHEMA_VERSION,
            "summary": {"team": team, "season": season, "record": f"{wins}-{losses}-{ties}", "games_played": played,
                        "win_pct": round((wins + .5 * ties) / played, 3) if played else None,
                        "points_for": pf, "points_against": pa},
            "statistics": total, "defense_allowed": defensive, "games": team_games}


def collect(season, output_dir, fetcher, publish_latest=True):
    schedule = fetcher.get(SCHEDULE_URL)
    games = normalize_schedule(schedule, season)
    weekly_text = fetcher.get(STATS_URL.format(level="week", season=season), optional=True)
    total_text = fetcher.get(STATS_URL.format(level="reg", season=season), optional=True)
    weekly = normalize_stats(weekly_text, season, "week") if weekly_text is not None else []
    totals = normalize_stats(total_text, season, "reg") if total_text is not None else []
    quality = validate_join(games, weekly, totals)
    base = Path(output_dir)
    season_dir = base / "seasons" / str(season)
    teams = {"schema_version": SCHEMA_VERSION, "season": season,
             "teams": [{"team": team, "key": team.lower(), "name": TEAM_NAMES[team]} for team in sorted(TEAM_NAMES)]}
    payloads = {"teams.json": teams,
                "schedule.json": {"schema_version": SCHEMA_VERSION, "season": season, "season_type": "REG", "games": games},
                "team_stats.json": {"schema_version": SCHEMA_VERSION, "season": season, "season_type": "REG", "teams": totals, "weekly": weekly}}
    for team in sorted(TEAM_NAMES):
        payload = team_payload(team, season, games, weekly, totals)
        for key in [team.lower()] + OUTPUT_ALIASES.get(team, []):
            payloads[key + ".json"] = payload
    # Keep the historical data.json path as a current-season raw bundle.
    payloads["data.json"] = {"schema_version": SCHEMA_VERSION, "season": season, "schedule": games, "team_statistics": totals, "weekly_statistics": weekly, "quality": quality}
    core = {"schema_version": SCHEMA_VERSION, "season": season, "season_type": "REG", "schedule_games": len(games),
            "completed_games": sum(g["status"] == "final" for g in games), "team_count": len(TEAM_NAMES),
            "weekly_stat_records": len(weekly), "season_stat_teams": len(totals), "quality": quality,
            "statistics_status": "pending" if not totals else "partial" if any(quality.values()) else "available",
            "sources": fetcher.sources,
            "files_sha256": {name: hashlib.sha256(json_bytes(data)).hexdigest() for name, data in sorted(payloads.items())}}
    previous_path = season_dir / "manifest.json"
    previous = json.loads(previous_path.read_text()) if previous_path.exists() else {}
    same = {k: v for k, v in previous.items() if k != "collected_at"} == core
    manifest = dict(core, collected_at=previous["collected_at"] if same else datetime.now(timezone.utc).isoformat())
    payloads["manifest.json"] = manifest
    changed = 0
    for name, data in payloads.items():
        encoded = json_bytes(data)
        changed += write_if_changed(season_dir / name, encoded)
        if publish_latest:
            changed += write_if_changed(base / name, encoded)
    print(f"{season}: {len(games)} games, {core['completed_games']} final, {len(totals)} team stat totals, {len(weekly)} weekly records; {changed} files changed")
    if any(quality.values()):
        print("WARNING: upstream statistics lag schedule results: " + json.dumps(quality), file=sys.stderr)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, default=2026)
    parser.add_argument("--output-dir", type=Path, default=Path("docs"))
    parser.add_argument("--cache-dir", type=Path, default=Path(".cache/nflverse"))
    parser.add_argument("--no-publish-latest", action="store_true", help="Update only the season directory; leave active-season files unchanged")
    args = parser.parse_args()
    if args.season < 2021:
        parser.error("This pipeline validates the 17-game, 272-game schedule used since 2021")
    try:
        collect(args.season, args.output_dir, Fetcher(args.cache_dir), not args.no_publish_latest)
    except (DataError, requests.RequestException) as exc:
        parser.exit(1, f"Collection failed; published data preserved: {exc}\n")


if __name__ == "__main__":
    main()
