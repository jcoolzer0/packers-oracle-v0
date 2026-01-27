import json
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import nflreadpy as nfl

SEASON = 2025
OUT_DIR = Path("docs")

# Canonical lowercase keys for JSON filenames
# Keep these stable; they are the "API" your visualizer consumes.
TEAM_ALIAS = {
    # Common tricky ones / synonyms
    "GB": "gb",
    "GNB": "gb",
    "PHI": "phi",

    # LA teams (RAMS)
    "LA": "lar",          # Rams canonical
    "LAR": "lar",
    "RAMS": "lar",
    "LOS ANGELES RAMS": "lar",

    # CHARGERS
    "LAC": "lac",         # Chargers canonical
    "LACH": "lac",
    "CHARGERS": "lac",
    "LOS ANGELES CHARGERS": "lac",

    # A few other common alt codes (harmless)
    "JAX": "jax",
    "WSH": "wsh",
    "WAS": "wsh",
}

# For backwards compatibility: also emit these filenames as copies.
# Example: canonical "lar.json" also written out as "la.json" (and optionally "LA.json")
EXTRA_OUTPUT_ALIASES = {
    "lar": ["la"],   # keep old code paths working
    # add more if needed later
}

# Strict whitelist to prevent "AFC/NFC", Pro Bowl, preseason artifacts, or placeholders
NFL_TEAMS_32 = {
    "ARI","ATL","BAL","BUF","CAR","CHI","CIN","CLE","DAL","DEN","DET","GB",
    "HOU","IND","JAX","KC","LAC","LAR","LV","MIA","MIN","NE","NO","NYG",
    "NYJ","PHI","PIT","SEA","SF","TB","TEN","WAS"
}

def _alias(team: str) -> str:
    if team is None:
        return "unknown"
    s = str(team).strip()
    up = s.upper()
    if up in TEAM_ALIAS:
        return TEAM_ALIAS[up]
    return s.lower()

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
    strength = min(1.0, abs(p_win - 0.5) * 2.0)
    sample = np.log1p(n) / np.log1p(12)
    conf = 35 + 65 * (0.15 + 0.85 * strength) * sample
    return clamp(conf, 0, 100)

def win_loss_coherence_grade(conf, result, p_win):
    if result is None or p_win is None or conf is None:
        return None

    predicted = "W" if p_win >= 0.5 else "L"
    match = (result == predicted)

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

def _write_json(path: Path, payload: dict):
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

def _write_with_alias_copies(canonical_key: str, payload: dict):
    """
    Always write docs/<canonical_key>.json
    Then write any EXTRA_OUTPUT_ALIASES copies (e.g., la.json for lar.json)
    """
    canonical_path = OUT_DIR / f"{canonical_key}.json"
    _write_json(canonical_path, payload)

    # Lowercase alias copies
    for alt in EXTRA_OUTPUT_ALIASES.get(canonical_key, []):
        alt_path = OUT_DIR / f"{alt}.json"
        _write_json(alt_path, payload)

    # OPTIONAL: also write an uppercase variant if something still references it
    if canonical_key == "lar":
        upper_path = OUT_DIR / "LA.json"
        _write_json(upper_path, payload)

# ------------------------- Playoff-safe schedule normalization -------------------------

def _first_existing(df: pd.DataFrame, candidates):
    for c in candidates:
        if c in df.columns:
            return c
    return None

def _get_game_type_row(r: pd.Series) -> str:
    # Normalize possible columns to one uppercase token
    for c in ["game_type", "season_type"]:
        if c in r.index:
            v = r.get(c)
            if v is not None and not pd.isna(v):
                return str(v).strip().upper()
    return ""

def _to_int_or_none(x):
    try:
        if x is None or pd.isna(x):
            return None
        # handles strings like "19"
        return int(float(x))
    except Exception:
        return None

def _derive_week_num(df: pd.DataFrame) -> pd.Series:
    """
    Create a robust numeric week for both REG and POST.
    - If week is numeric, use it.
    - Else if it's POST and we can infer the round, map to 19..22.
    """
    week_col = "week" if "week" in df.columns else None

    # Start with numeric week where possible
    if week_col:
        w = pd.to_numeric(df[week_col], errors="coerce")
    else:
        w = pd.Series([np.nan] * len(df), index=df.index)

    week_num = w.astype("float")

    # If week missing on some rows, try derive from postseason round tokens
    # Common tokens you may see: WC/DIV/CON/SB or POST1/POST2 or "POST"
    # We'll only map if it's clearly postseason and week is NaN.
    def map_post_round(r):
        if pd.notna(r.get("week_num")):
            return r.get("week_num")

        gt = _get_game_type_row(r)

        # Some feeds store exact rounds:
        if gt in {"WC", "WILD", "WILDCARD"}:
            return 19
        if gt in {"DIV", "DIVISIONAL"}:
            return 20
        if gt in {"CON", "CONF", "CONFCHAMP", "CONFERENCE"}:
            return 21
        if gt in {"SB", "SUPERBOWL"}:
            return 22

        # If it's just "POST", try to infer from a "week" string if present like "post-1"
        # Or from any round-like field names.
        for c in ["week", "week_id", "game_week", "schedule_week", "game_label", "week_name"]:
            if c in r.index:
                v = r.get(c)
                if v is None or pd.isna(v):
                    continue
                s = str(v).lower()
                if "post-1" in s or "wild" in s or "wc" in s:
                    return 19
                if "post-2" in s or "div" in s:
                    return 20
                if "post-3" in s or "conf" in s or "champ" in s:
                    return 21
                if "post-4" in s or "super" in s or "sb" in s:
                    return 22

        # If cannot infer, leave NaN
        return np.nan

    tmp = df.copy()
    tmp["week_num"] = week_num
    tmp["week_num"] = tmp.apply(map_post_round, axis=1)
    tmp["week_num"] = pd.to_numeric(tmp["week_num"], errors="coerce")

    return tmp["week_num"]

def _filter_real_games_only(sched: pd.DataFrame) -> pd.DataFrame:
    """
    Keep only rows that represent real NFL team-vs-team games
    (prevents Pro Bowl / AFC-NFC / placeholders).
    Also removes preseason if tagged.
    """
    df = sched.copy()

    # Normalize team codes to upper strings
    df["home_team"] = df["home_team"].astype(str).str.upper()
    df["away_team"] = df["away_team"].astype(str).str.upper()

    # Drop non-32-team rows (AFC/NFC, TBD, nan strings, etc.)
    df = df[df["home_team"].isin(NFL_TEAMS_32) & df["away_team"].isin(NFL_TEAMS_32)].copy()

    # Filter by game/season type if present
    # Keep REG and postseason; drop PRE if it exists.
    type_col = _first_existing(df, ["game_type", "season_type"])
    if type_col:
        gt = df[type_col].astype(str).str.upper()

        # Keep common regular + post tokens; ignore unknowns rather than risking dropping valid games.
        # If your feed uses "POST" only, we keep it.
        keep = gt.isin({"REG", "POST", "WC", "DIV", "CON", "SB"})
        # If none match (unexpected schema), don't filter further.
        if keep.any():
            df = df[keep].copy()

    return df

# --------------------------------------------------------------------------------------

def build():
    OUT_DIR.mkdir(exist_ok=True)

    # Load schedule (polars -> pandas). pyarrow required.
    sched = nfl.load_schedules([SEASON]).to_pandas()

    home_col = "home_score" if "home_score" in sched.columns else ("home_points" if "home_points" in sched.columns else None)
    away_col = "away_score" if "away_score" in sched.columns else ("away_points" if "away_points" in sched.columns else None)
    if home_col is None or away_col is None:
        raise RuntimeError("Could not find home/away score columns in schedule data.")

    # NEW: Filter + normalize week for playoff safety
    sched = _filter_real_games_only(sched)

    # If nothing left after filtering, fail loudly (better than silently producing empty docs)
    if sched.empty:
        raise RuntimeError("Schedule became empty after filtering to real NFL games. Check feed schema/columns.")

    # Create robust numeric week
    sched["week_num"] = _derive_week_num(sched)

    # Drop rows we cannot place on a timeline (rare, but safe)
    sched = sched[pd.notna(sched["week_num"])].copy()
    sched["week_num"] = sched["week_num"].astype(int)

    # Sort chronologically enough for weekly batching
    sort_cols = ["week_num"]
    if "game_id" in sched.columns:
        sort_cols.append("game_id")
    sched = sched.sort_values(sort_cols).reset_index(drop=True)

    # Determine all teams in this dataset
    all_teams = sorted(set(sched["home_team"]).union(set(sched["away_team"])))

    team_pf_hist = {t: [] for t in all_teams}
    team_pa_hist = {t: [] for t in all_teams}
    team_games_hist = {t: [] for t in all_teams}

    library = {}
    team_out = {t: {"summary": {"team": t, "season": SEASON}, "games": []} for t in all_teams}

    def team_stats_before_week(team, week_num, recent_k=3):
        hist = [g for g in team_games_hist[team] if g["week"] < week_num]
        n = len(hist)
        if n == 0:
            return {"n": 0, "pdpg": 0.0, "form": 0.0}
        pf = np.array([g["pf"] for g in hist], dtype=float)
        pa = np.array([g["pa"] for g in hist], dtype=float)
        pdpg = float(np.mean(pf - pa))
        recent = hist[-recent_k:]
        recent_pd = float(np.mean([g["pf"] - g["pa"] for g in recent])) if recent else 0.0
        return {"n": n, "pdpg": pdpg, "form": recent_pd}

    def make_bucket(is_home, team_pdpg, opp_pdpg, team_form, opp_form):
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

    # IMPORTANT: now we use week_num
    weeks = sorted(sched["week_num"].dropna().astype(int).unique().tolist())

    for week in weeks:
        week_games = sched[sched["week_num"].astype(int) == week].copy()
        pregame_records = []

        for _, r in week_games.iterrows():
            home = str(r["home_team"])
            away = str(r["away_team"])

            hs = r.get(home_col)
            aw = r.get(away_col)
            played = not (pd.isna(hs) or pd.isna(aw))

            home_stats = team_stats_before_week(home, week)
            away_stats = team_stats_before_week(away, week)

            home_bucket = make_bucket(True, home_stats["pdpg"], away_stats["pdpg"], home_stats["form"], away_stats["form"])
            home_hist = library_lookup(home_bucket)
            home_hist_norm = None
            home_p = None
            home_conf = None
            if home_hist and home_hist.get("n", 0) > 0:
                n = home_hist["n"]
                w_ = home_hist["W"] / n
                l_ = home_hist["L"] / n
                t_ = home_hist["T"] / n
                home_hist_norm = {"n": n, "W": round(w_, 3), "L": round(l_, 3), "T": round(t_, 3)}
                home_p = wl_expectation_from_hist(home_hist_norm)
                home_conf = pregame_confidence(home_p, n)

            away_bucket = make_bucket(False, away_stats["pdpg"], home_stats["pdpg"], away_stats["form"], home_stats["form"])
            away_hist = library_lookup(away_bucket)
            away_hist_norm = None
            away_p = None
            away_conf = None
            if away_hist and away_hist.get("n", 0) > 0:
                n = away_hist["n"]
                w_ = away_hist["W"] / n
                l_ = away_hist["L"] / n
                t_ = away_hist["T"] / n
                away_hist_norm = {"n": n, "W": round(w_, 3), "L": round(l_, 3), "T": round(t_, 3)}
                away_p = wl_expectation_from_hist(away_hist_norm)
                away_conf = pregame_confidence(away_p, n)

            if played:
                hs = int(hs)
                aw = int(aw)
                if hs > aw:
                    home_res = "W"; away_res = "L"
                elif hs < aw:
                    home_res = "L"; away_res = "W"
                else:
                    home_res = "T"; away_res = "T"
            else:
                home_res = None
                away_res = None

            def pack_game(team, opp, is_home, pf, pa, result, p_win, conf, hist_norm, bucket):
                coherence = None
                if result is not None:
                    pf_arr = np.array(team_pf_hist[team] + [pf], dtype=float)
                    pa_arr = np.array(team_pa_hist[team] + [pa], dtype=float)
                    off_score = to_score(zscore(pf_arr)[-1])
                    def_score = to_score(zscore(-pa_arr)[-1])
                    sig = np.array([off_score, def_score], dtype=float)

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

                pick = None
                if p_win is not None:
                    pick = "W" if p_win >= 0.5 else "L"

                reality_lock = None
                if result is not None and hist_norm and hist_norm.get("n", 0) > 0 and pick is not None:
                    reality_lock = "MATCH" if result == pick else "DIVERGE"

                wlc = win_loss_coherence_grade(conf, result, p_win)
                explain_pre = explain_pregame(team, opp, is_home, p_win, conf, hist_norm)

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
                        "pregame_pick": pick,
                        "pregame_expected_win_rate": None if p_win is None else round(float(p_win), 3),
                        "pregame_confidence": None if conf is None else round(float(conf), 1),
                        "pregame_historical_map": hist_norm,
                        "pregame_bucket": None,
                        "explain_pregame": explain_pre,

                        "coherence": coherence,
                        "reality_lock": reality_lock,
                        "win_loss_coherence": wlc,
                        "explain": explain_post,
                    }
                }, bucket

            if played:
                home_pf, home_pa = hs, aw
                away_pf, away_pa = aw, hs
            else:
                home_pf = home_pa = away_pf = away_pa = None

            home_game, home_bucket_for_update = pack_game(home, away, True, home_pf, home_pa, home_res, home_p, home_conf, home_hist_norm, home_bucket)
            away_game, away_bucket_for_update = pack_game(away, home, False, away_pf, away_pa, away_res, away_p, away_conf, away_hist_norm, away_bucket)

            team_out[home]["games"].append(home_game)
            team_out[away]["games"].append(away_game)

            if played:
                pregame_records.append((home_bucket_for_update, home_res))
                pregame_records.append((away_bucket_for_update, away_res))

        # Update the league library AFTER the week (no leakage within same week_num)
        for bucket, res in pregame_records:
            library_update(bucket, res)

        # Update per-team histories from played games in this week
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

            team_pf_hist[home].append(hs); team_pa_hist[home].append(aw)
            team_pf_hist[away].append(aw); team_pa_hist[away].append(hs)

    # --- Write teams.json ---
    # IMPORTANT: "key" is what the visualizer uses to fetch ./<key>.json
    teams_payload = [{"team": t, "key": _alias(t)} for t in all_teams]
    _write_json(OUT_DIR / "teams.json", {"season": SEASON, "teams": teams_payload})

    # --- Write per-team JSONs (plus alias copies) ---
    for t in all_teams:
        games = sorted(team_out[t]["games"], key=lambda g: g["week"])
        played = [g for g in games if g["result"] is not None]

        w = sum(1 for g in played if g["result"] == "W")
        l = sum(1 for g in played if g["result"] == "L")
        ti = sum(1 for g in played if g["result"] == "T")
        n = len(played)
        win_pct = (w + 0.5 * ti) / n if n else None

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

        key = _alias(t)
        _write_with_alias_copies(key, payload)

def main():
    build()

if __name__ == "__main__":
    main()
