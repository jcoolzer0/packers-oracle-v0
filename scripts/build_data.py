import json
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import nflreadpy as nfl

SEASON = 2025
OUT_DIR = Path("docs")

TEAMS = {
    "GB": "gb.json",
    "PHI": "phi.json"
}

def zscore(x):
    x = np.asarray(x, dtype=float)
    mu = np.nanmean(x)
    sd = np.nanstd(x) + 1e-6
    return (x - mu) / sd

def to_score(z):
    s = 1 / (1 + np.exp(-z))
    return float(30 + 70 * s)

def win_loss_coherence(coh, result, expected):
    if coh is None or result is None:
        return None

    if expected is None:
        label = "Uncalibrated"
    elif result == "W" and expected >= 0.6:
        label = "Aligned Win"
    elif result == "L" and expected <= 0.4:
        label = "Aligned Loss"
    elif result == "W":
        label = "Scrappy Win"
    elif result == "L":
        label = "Coherent Loss"
    else:
        label = "Neutral"

    if coh >= 85:
        grade = "A"
    elif coh >= 75:
        grade = "B"
    elif coh >= 65:
        grade = "C"
    elif coh >= 55:
        grade = "D"
    else:
        grade = "F"

    return {
        "grade": grade,
        "label": label
    }

def explain_game(coh, result, expected):
    if result is None:
        return "Upcoming game. Oracle has not evaluated performance yet."

    parts = []
    parts.append(f"Performance coherence was {round(coh)}.")

    if expected is None:
        parts.append("Oracle had no similar historical games to form an expectation.")
    else:
        parts.append(f"Historically similar games won about {round(expected * 100)}% of the time.")

    if result == "W":
        parts.append("The team won this game.")
    elif result == "L":
        parts.append("The team lost this game.")
    else:
        parts.append("The game ended in a tie.")

    return " ".join(parts)

def build_team(team, out_name):
    sched = nfl.load_schedules([SEASON]).to_pandas()

    g = sched[(sched["home_team"] == team) | (sched["away_team"] == team)].copy()
    g["is_home"] = g["home_team"] == team
    g["opponent"] = np.where(g["is_home"], g["away_team"], g["home_team"])

    home_col = "home_score" if "home_score" in g.columns else "home_points"
    away_col = "away_score" if "away_score" in g.columns else "away_points"

    rows = []
    for _, r in g.sort_values("week").iterrows():
        hs = r.get(home_col)
        aw = r.get(away_col)

        if np.isnan(hs) or np.isnan(aw):
            rows.append({
                "week": int(r["week"]),
                "opponent": str(r["opponent"]),
                "result": None,
                "score": None
            })
        else:
            pf = int(hs if r["is_home"] else aw)
            pa = int(aw if r["is_home"] else hs)
            if pf > pa:
                res = "W"
            elif pf < pa:
                res = "L"
            else:
                res = "T"

            rows.append({
                "week": int(r["week"]),
                "opponent": str(r["opponent"]),
                "result": res,
                "score": f"{pf}-{pa}"
            })

    played = [r for r in rows if r["result"] is not None]
    pf = np.array([int(r["score"].split("-")[0]) for r in played])
    pa = np.array([int(r["score"].split("-")[1]) for r in played])

    off = [to_score(z) for z in zscore(pf)]
    deff = [to_score(z) for z in zscore(-pa)]
    sig = np.vstack([off, deff]).T

    mean = sig.mean(axis=0)
    std = sig.std(axis=0) + 1e-6

    bins = [tuple(int(v // 10) for v in s) for s in sig]
    outcomes = [r["result"] for r in played]

    cal = 0
    cal_trail = []

    for i, r in enumerate(played):
        dist = np.sqrt(np.mean(((sig[i] - mean) / std) ** 2))
        coh = max(0, min(100, 95 - 25 * dist))

        past = [j for j in range(i) if bins[j] == bins[i]]
        if past:
            w = sum(1 for j in past if outcomes[j] == "W")
            l = sum(1 for j in past if outcomes[j] == "L")
            t = sum(1 for j in past if outcomes[j] == "T")
            n = len(past)
            hist = {"n": n, "W": round(w / n, 3), "L": round(l / n, 3), "T": round(t / n, 3)}
            expected = hist["W"] + 0.5 * hist["T"]
            predicted = "W" if expected >= 0.5 else "L"
            lock = "MATCH" if r["result"] == predicted else "DIVERGE"
            cal += 1 if lock == "MATCH" else -1
        else:
            hist = None
            expected = None
            lock = None

        cal_trail.append(cal)

        r["oracle"] = {
            "coherence": round(coh, 1),
            "historical_map": hist,
            "reality_lock": lock,
            "win_loss_coherence": win_loss_coherence(coh, r["result"], expected),
            "explain": explain_game(coh, r["result"], expected)
        }

    it = iter(played)
    games_out = []
    for r in rows:
        if r["result"] is None:
            games_out.append({
                **r,
                "oracle": {
                    "coherence": None,
                    "historical_map": None,
                    "reality_lock": None,
                    "win_loss_coherence": None,
                    "explain": "Upcoming game. Oracle has not evaluated performance yet."
                }
            })
        else:
            games_out.append(next(it))

    w = sum(1 for r in played if r["result"] == "W")
    l = sum(1 for r in played if r["result"] == "L")
    t = sum(1 for r in played if r["result"] == "T")
    n = len(played)
    win_pct = (w + 0.5 * t) / n if n else None

    payload = {
        "summary": {
            "team": team,
            "season": SEASON,
            "record": f"{w}-{l}-{t}",
            "win_pct": round(win_pct, 3),
            "calibration_score": cal,
            "calibration_trail": cal_trail
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "games": games_out
    }

    OUT_DIR.mkdir(exist_ok=True)
    (OUT_DIR / out_name).write_text(json.dumps(payload, indent=2), encoding="utf-8")

def main():
    for team, out in TEAMS.items():
        build_team(team, out)

if __name__ == "__main__":
    main()
