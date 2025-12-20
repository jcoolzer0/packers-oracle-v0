import json
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import nflreadpy as nfl

SEASON = 2025
OUT_DIR = Path("docs")

# We will generate a file per team: docs/<team>.json  (e.g., gb.json, phi.json, etc.)
# And a lightweight list: docs/teams.json for the web dropdown.
TEAM_ALIAS = {
    "GB": "gb",
    "PHI": "phi",
}

def _alias(team: str) -> str:
    return TEAM_ALIAS.get(team, team.lower())

def zscore(x):
    x = np.asarray(x, dtype=float)
    mu = np.nanmean(x) if np.isfinite(np.nanmean(x)) else 0.0
    sd = np.nanstd(x) + 1e-6
    return (x - mu) / sd

def to_score(z):
    # map z -> 30..100
    s = 1 / (1 + np.exp(-z))
    return float(30 + 70 * s)

def clamp(x, lo, hi):
    return float(max(lo, min(hi, x)))

def bucketize(v, step=3):
    # integer bucket bins (wider bins => fewer null historical maps)
    return int(np.floor(v / step))

def wl_expectation_from_hist(hist):
    if not hist or not hist.get("n"):
        return None
    w = hist.get("W", 0.0)
    t = hist.get("T", 0.0)
    return w + 0.5 * t

def pregame_confidence(p_win, n):
    """
    Confidence from:
      - sample size n
      - how far p_win is from 0.5
    """
    if p_win is None or n is None or n <= 0:
        return None
    # strength: 0..1 (0 at 0.5, 1 at 0 or 1)
    strength = min(1.0, abs(p_win - 0.5) * 2.0)
    # sample factor: 0..1 saturating around n~12
    sample = np.log1p(n) / np.log1p(12)
    conf = 35 + 65 * (0.15 + 0.85 * strength) * sample
    return clamp(conf, 0, 100)

def win_loss_coherence_grade(conf, result, p_win):
    """
    A simple "W/L coherence constellation":
    - It evaluates whether outcome aligns with pregame expectation AND the confidence strength.
    """
    if result is None or p_win is None or conf is None:
        return None

    predicted = "W" if p_win >= 0.5 else "L"
    match = (result == predicted)

    # Grade based on confidence + match
    # high confidence miss hurts, high confidence hit is great.
    if match:
        if conf >= 80: grade = "A"
        elif conf >= 65: grade = "B"
        elif conf >= 50: grade = "C"
        else: grade = "D"
        label = "Aligned"
    else:
        if conf >= 80: grade = "F"
        elif conf >= 65: grade = "D"
        elif conf >= 50: grade = "C"
        else: grade = "B"
        label = "Diverged"

    return {"grade": grade, "label": label, "predicted": predicted}

def explain_pregame(team, opp, is_home, p_win, conf, hist):
    ha = "home" if is_home else "away"
    if p_win is None or conf is None or not hist or not hist.get("n"):
        return f"Pregame read: {team} ({ha}) vs {opp}. Oracle has insufficient similar-history, so it withholds a win/loss confidence."
    n = hist["n"]
    return (
        f"Pregame read: {team} ({ha}) vs {opp}. "
        f"In {n} historically similar situations (league-wide), teams won about {int(round(p_win*100))}% of the time. "
        f"Confidence: {int(round(conf))}/100."
    )

def build():
    OUT_DIR.mkdir(exist_ok=True)

    # Load schedule (polars -> pandas). pyarrow required.
    sched = nfl.load_schedules([SEASON]).to_pandas()

    # Normalize columns we care about
    # nflreadpy schedules typically include: week, game_id, home_team, away_team, home_score/home_points, away_score/away_points, gametime
    home_col = "home_score" if "home_score" in sched.columns else ("home_points" if "home_points" in sched.columns else None)
    away_col = "away_score" if "away_score" in sched.columns else ("away_points" if "away_points" in sched.columns else None)

    if home_col is None or away_col is None:
        raise RuntimeError("Could not find home/away score columns in schedule data.")

    # Sort chronologically enough for weekly batching
    # We will enforce NO leakage within a week by training only on prior weeks.
    sched = sched.sort_values(["week", "game_id"]).reset_index(drop=True)

    # Determine all teams in this dataset
    all_teams = sorted(set(sched["home_team"]).union(set(sched["away_team"])))

    # For per-team postgame coherence we track each team’s PF/PA history over played games
    team_pf_hist = {t: [] for t in all_teams}
    team_pa_hist = {t: [] for t in all_teams}

    # Pregame rolling features: for each team, keep prior games (pf, pa)
    team_games_hist = {t: [] for t in all_teams}  # list of dicts {week,pf,pa,result}

    # League-wide pregame library: maps pregame bucket -> counts of outcomes
    library = {}  # bucket -> {"W":x,"L":y,"T":z,"n":n}

    # Output structure per team (we’ll fill games then write)
    team_out = {t: {"summary": {"team": t, "season": SEASON}, "games": []} for t in all_teams}

    def team_stats_before_week(team, week, recent_k=3):
        """Stats using only games BEFORE this week."""
        hist = [g for g in team_games_hist[team] if g["week"] < week]
        n = len(hist)
        if n == 0:
            return {"n": 0, "pdpg": 0.0, "form": 0.0}
        pf = np.array([g["pf"] for g in hist], dtype=float)
        pa = np.array([g["pa"] for g in hist], dtype=float)
        pdpg = float(np.mean(pf - pa))
        recent = hist[-recent_k:]
        if recent:
            recent_pd = float(np.mean([g["pf"] - g["pa"] for g in recent]))
        else:
            recent_pd = 0.0
        return {"n": n, "pdpg": pdpg, "form": recent_pd}

    def make_bucket(is_home, team_pdpg, opp_pdpg, team_form, opp_form):
        # Wider bins keeps more matches early season.
        return (
            int(is_home),
            bucketize(team_pdpg, step=3),
            bucketize(opp_pdpg, step=3),
            bucketize(team_form, step=3),
            bucketize(opp_form, step=3),
        )

    def library_lookup(bucket):
        return library.get(bucket)

    def library_update(bucket, result):
        if bucket not in library:
            library[bucket] = {"W": 0, "L": 0, "T": 0, "n": 0}
        library[bucket][result] += 1
        library[bucket]["n"] += 1

    # We'll process week by week to prevent same-week leakage.
    weeks = sorted(sched["week"].dropna().astype(int).unique().tolist())

    for week in weeks:
        week_games = sched[sched["week"].astype(int) == week].copy()

        # --- PREGAME: compute reads using library built from prior weeks only ---
        pregame_records = []  # store per-game pregame bucket so we can update library after week completes

        for _, r in week_games.iterrows():
            home = str(r["home_team"])
            away = str(r["away_team"])

            hs = r.get(home_col)
            aw = r.get(away_col)
            played = not (pd.isna(hs) or pd.isna(aw))

            # Pregame stats from prior weeks only
            home_stats = team_stats_before_week(home, week)
            away_stats = team_stats_before_week(away, week)

            # For each team's perspective, compute bucket and expectation from league library
            # Home perspective
            home_bucket = make_bucket(
                True,
                home_stats["pdpg"],
                away_stats["pdpg"],
                home_stats["form"],
                away_stats["form"],
            )
            home_hist = library_lookup(home_bucket)
            home_hist_norm = None
            home_p = None
            home_conf = None

            if home_hist and home_hist.get("n", 0) > 0:
                n = home_hist["n"]
                w = home_hist["W"] / n
                l = home_hist["L"] / n
                t = home_hist["T"] / n
                home_hist_norm = {"n": n, "W": round(w, 3), "L": round(l, 3), "T": round(t, 3)}
                home_p = wl_expectation_from_hist(home_hist_norm)
                home_conf = pregame_confidence(home_p, n)

            # Away perspective
            away_bucket = make_bucket(
                False,
                away_stats["pdpg"],
                home_stats["pdpg"],
                away_stats["form"],
                home_stats["form"],
            )
            away_hist = library_lookup(away_bucket)
            away_hist_norm = None
            away_p = None
            away_conf = None

            if away_hist and away_hist.get("n", 0) > 0:
                n = away_hist["n"]
                w = away_hist["W"] / n
                l = away_hist["L"] / n
                t = away_hist["T"] / n
                away_hist_norm = {"n": n, "W": round(w, 3), "L": round(l, 3), "T": round(t, 3)}
                away_p = wl_expectation_from_hist(away_hist_norm)
                away_conf = pregame_confidence(away_p, n)

            # Determine result if played
            if played:
                hs = int(hs)
                aw = int(aw)
                # From home perspective:
                if hs > aw:
                    home_res = "W"
                    away_res = "L"
                elif hs < aw:
                    home_res = "L"
                    away_res = "W"
                else:
                    home_res = "T"
                    away_res = "T"
            else:
                home_res = None
                away_res = None

            # Prepare postgame coherence later (only for played)
            # Store each team's game record output
            def pack_game(team, opp, is_home, pf, pa, result, p_win, conf, hist_norm, bucket):
                # Postgame coherence from team’s own PF/PA distribution so far (played games only)
                coherence = None
                if result is not None:
                    # Build a coherence signal based on PF and PA compared to that team’s played history
                    pf_arr = np.array(team_pf_hist[team] + [pf], dtype=float)
                    pa_arr = np.array(team_pa_hist[team] + [pa], dtype=float)

                    # If early season, avoid NaN std edge
                    off_score = to_score(zscore(pf_arr)[-1])
                    def_score = to_score(zscore(-pa_arr)[-1])

                    # combine in a distance-from-mean style
                    sig = np.array([off_score, def_score], dtype=float)
                    # mean/std from historical played only (if exists), else from itself
                    if len(team_pf_hist[team]) >= 2:
                        off_hist = [to_score(z) for z in zscore(np.array(team_pf_hist[team], dtype=float))]
                        def_hist = [to_score(z) for z in zscore(-np.array(team_pa_hist[team], dtype=float))]
                        mu = np.array([np.mean(off_hist), np.mean(def_hist)], dtype=float)
                        sd = np.array([np.std(off_hist) + 1e-6, np.std(def_hist) + 1e-6], dtype=float)
                    else:
                        mu = sig
                        sd = np.array([1.0, 1.0], dtype=float)

                    dist = float(np.sqrt(np.mean(((sig - mu) / sd) ** 2)))
                    coherence = round(clamp(95 - 25 * dist, 0, 100), 1)

                # Pregame pick
                pick = None
                if p_win is not None:
                    pick = "W" if p_win >= 0.5 else "L"

                # Reality lock for pregame expectation when hist exists
                reality_lock = None
                if result is not None and hist_norm and hist_norm.get("n", 0) > 0 and pick is not None:
                    reality_lock = "MATCH" if result == pick else "DIVERGE"

                wlc = win_loss_coherence_grade(conf, result, p_win)

                explain_pre = explain_pregame(team, opp, is_home, p_win, conf, hist_norm)

                explain_post = None
                if result is None:
                    explain_post = "Upcoming game. Postgame coherence will appear after the game is played."
                else:
                    if hist_norm and hist_norm.get("n", 0) > 0:
                        explain_post = (
                            f"Postgame: coherence {coherence}. "
                            f"Pregame expected win rate was ~{int(round(p_win*100))}% (n={hist_norm['n']}), "
                            f"and reality lock is {reality_lock}."
                        )
                    else:
                        explain_post = f"Postgame: coherence {coherence}. Oracle had insufficient similar-history pregame, so no reality lock was claimed."

                return {
                    "week": int(week),
                    "opponent": opp,
                    "result": result,
                    "score": None if result is None else f"{pf}-{pa}",
                    "oracle": {
                        # Pregame oracle (league-wide learned, past-only)
                        "pregame_pick": pick,
                        "pregame_expected_win_rate": None if p_win is None else round(float(p_win), 3),
                        "pregame_confidence": None if conf is None else round(float(conf), 1),
                        "pregame_historical_map": hist_norm,
                        "pregame_bucket": None,  # keep schema simple; can add later for debugging
                        "explain_pregame": explain_pre,

                        # Postgame oracle (team-coherence)
                        "coherence": coherence,
                        "reality_lock": reality_lock,
                        "win_loss_coherence": wlc,
                        "explain": explain_post,
                    }
                }, bucket

            # Home game record
            if played:
                home_pf, home_pa = hs, aw
                away_pf, away_pa = aw, hs
            else:
                home_pf = home_pa = away_pf = away_pa = None

            home_game, home_bucket_for_update = pack_game(
                home, away, True,
                home_pf, home_pa,
                home_res,
                home_p, home_conf,
                home_hist_norm,
                home_bucket
            )
            away_game, away_bucket_for_update = pack_game(
                away, home, False,
                away_pf, away_pa,
                away_res,
                away_p, away_conf,
                away_hist_norm,
                away_bucket
            )

            team_out[home]["games"].append(home_game)
            team_out[away]["games"].append(away_game)

            # Stash for library update AFTER the week, only if played
            if played:
                pregame_records.append((home_bucket_for_update, home_res))
                pregame_records.append((away_bucket_for_update, away_res))

        # --- AFTER WEEK: update league library and per-team histories with outcomes (no leakage within week) ---
        for bucket, res in pregame_records:
            library_update(bucket, res)

        # Update team histories from played games in this week
        for _, r in week_games.iterrows():
            home = str(r["home_team"])
            away = str(r["away_team"])
            hs = r.get(home_col)
            aw = r.get(away_col)
            if pd.isna(hs) or pd.isna(aw):
                continue
            hs = int(hs)
            aw = int(aw)
            if hs > aw:
                home_res, away_res = "W", "L"
            elif hs < aw:
                home_res, away_res = "L", "W"
            else:
                home_res = away_res = "T"

            team_games_hist[home].append({"week": int(week), "pf": hs, "pa": aw, "result": home_res})
            team_games_hist[away].append({"week": int(week), "pf": aw, "pa": hs, "result": away_res})

            # for postgame coherence baselines
            team_pf_hist[home].append(hs); team_pa_hist[home].append(aw)
            team_pf_hist[away].append(aw); team_pa_hist[away].append(hs)

    # --- Finalize summaries and write JSON files per team ---
    teams_payload = [{"team": t, "key": _alias(t)} for t in all_teams]
    (OUT_DIR / "teams.json").write_text(json.dumps({"season": SEASON, "teams": teams_payload}, indent=2), encoding="utf-8")

    for t in all_teams:
        games = sorted(team_out[t]["games"], key=lambda g: g["week"])
        played = [g for g in games if g["result"] is not None]

        w = sum(1 for g in played if g["result"] == "W")
        l = sum(1 for g in played if g["result"] == "L")
        ti = sum(1 for g in played if g["result"] == "T")
        n = len(played)
        win_pct = (w + 0.5 * ti) / n if n else None

        # calibration: count MATCH/DIVERGE only when reality_lock exists
        locks = [g["oracle"].get("reality_lock") for g in played]
        cal = 0
        trail = []
        for lk in locks:
            if lk == "MATCH":
                cal += 1
            elif lk == "DIVERGE":
                cal -= 1
            trail.append(cal)

        payload = {
            "summary": {
                "team": t,
                "season": SEASON,
                "record": f"{w}-{l}-{ti}",
                "win_pct": None if win_pct is None else round(float(win_pct), 3),
                "calibration_score": cal,
                "calibration_trail": trail,
                "note": "Pregame confidence is learned league-wide from prior weeks only (no same-week leakage)."
            },
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "games": games
        }

        (OUT_DIR / f"{_alias(t)}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

def main():
    build()

if __name__ == "__main__":
    main()
