
import json
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import nflreadpy as nfl

OUT = Path("docs/data.json")

TEAM = "GB"
SEASON = 2025

def zscore(x):
    x = np.asarray(x, dtype=float)
    mu = np.nanmean(x)
    sd = np.nanstd(x) + 1e-6
    return (x - mu) / sd

def to_score(z):
    # soft map z -> 0..100
    s = 1 / (1 + np.exp(-z))
    return float(30 + 70*s)

def main():
    sched = nfl.load_schedules([SEASON]).to_pandas()

    # games involving TEAM
    g = sched[(sched["home_team"] == TEAM) | (sched["away_team"] == TEAM)].copy()
    g["is_home"] = g["home_team"] == TEAM
    g["opponent"] = np.where(g["is_home"], g["away_team"], g["home_team"])

    # score cols can vary; try common ones
    home_score_col = "home_score" if "home_score" in g.columns else ("home_points" if "home_points" in g.columns else None)
    away_score_col = "away_score" if "away_score" in g.columns else ("away_points" if "away_points" in g.columns else None)

    def get_score(row, which):
        col = home_score_col if which == "home" else away_score_col
        if col is None or col not in g.columns:
            return None
        v = row.get(col)
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        return int(v)

    rows = []
    for _, r in g.sort_values("week").iterrows():
        hs = get_score(r, "home")
        aw = get_score(r, "away")

        if hs is None or aw is None:
            pf = pa = None
            res = None
            score = None
        else:
            if r["is_home"]:
                pf, pa = hs, aw
            else:
                pf, pa = aw, hs
            score = f"{pf}-{pa}"
            if pf > pa: res = "W"
            elif pf < pa: res = "L"
            else: res = "T"

        rows.append({
            "week": int(r["week"]),
            "opponent": str(r["opponent"]),
            "result": res,
            "score": score
        })

    # compute simple Oracle fields using only points for/against (v0)
    played = [x for x in rows if x["result"] is not None]
    pf = np.array([int(x["score"].split("-")[0]) for x in played], dtype=float)
    pa = np.array([int(x["score"].split("-")[1]) for x in played], dtype=float)

    off_z = zscore(pf)
    def_z = zscore(-pa)  # fewer allowed = better

    off = np.array([to_score(z) for z in off_z])
    deff = np.array([to_score(z) for z in def_z])

    # coherence: distance from baseline in (off,def) space
    sig = np.vstack([off, deff]).T
    mean = sig.mean(axis=0)
    std = sig.std(axis=0) + 1e-6

    def coherence(i):
        z = (sig[i] - mean) / std
        dist = float(np.sqrt(np.mean(z**2)))
        return float(max(0, min(100, 95 - 25*dist)))

    # historical map: bucket by coarse bins
    bins = [tuple(int(np.floor(v/10)) for v in sig[i]) for i in range(len(sig))]
    outs = [played[i]["result"] for i in range(len(sig))]

    cal = 0
    cal_trail = []

    for i in range(len(played)):
        coh = coherence(i)

        past = [j for j in range(i) if bins[j] == bins[i]]
        n = len(past)
        if n == 0:
            hm = None
            lock = None
        else:
            w = sum(1 for j in past if outs[j] == "W")
            l = sum(1 for j in past if outs[j] == "L")
            t = sum(1 for j in past if outs[j] == "T")
            hm = {"n": n, "W": round(w/n, 3), "L": round(l/n, 3), "T": round(t/n, 3)}

            expected = max([("W", hm["W"]), ("L", hm["L"]), ("T", hm["T"])], key=lambda kv: kv[1])[0]
            lock = "MATCH" if outs[i] == expected else "DIVERGE"
            cal += (1 if lock == "MATCH" else -1)

        cal_trail.append(cal)

        played[i]["oracle"] = {
            "coherence": round(coh, 1),
            "historical_map": hm,
            "reality_lock": lock
        }

    # merge oracle back into full list
    it = iter(played)
    games_out = []
    for x in rows:
        if x["result"] is None:
            games_out.append({**x, "oracle": {"coherence": None, "historical_map": None, "reality_lock": None}})
        else:
            games_out.append(next(it))

    w = sum(1 for x in played if x["result"] == "W")
    l = sum(1 for x in played if x["result"] == "L")
    t = sum(1 for x in played if x["result"] == "T")
    n = len(played)
    win_pct = (w + 0.5*t)/n if n else None

    payload = {
        "summary": {
            "team": TEAM,
            "season": SEASON,
            "record": f"{w}-{l}-{t}",
            "win_pct": round(win_pct, 3) if win_pct is not None else None,
            "calibration_score": cal,
            "calibration_trail": cal_trail
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "games": games_out
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")

if __name__ == "__main__":
    main()
