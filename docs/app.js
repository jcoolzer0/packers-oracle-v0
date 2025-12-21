let DATA = null;
let TEAMS = [];

// -------------------- helpers --------------------
function pct(x) {
  if (x === null || x === undefined) return "—";
  return Math.round(x * 100) + "%";
}

function bars(score) {
  if (score === null || score === undefined) return "—";
  const n = Math.max(0, Math.min(5, Math.round(score / 20)));
  return "▮".repeat(n) + "▯".repeat(5 - n);
}

function safeText(x) {
  return (x === null || x === undefined || x === "") ? "—" : String(x);
}

function outcomeLabel(result) {
  if (result === "W") return "Win";
  if (result === "L") return "Loss";
  if (result === "T") return "Tie";
  return "Upcoming";
}

function evidenceGradeFromN(n) {
  const nn = Number.isFinite(n) ? n : 0;
  if (nn >= 12) return "A";
  if (nn >= 6)  return "B";
  if (nn >= 2)  return "C";
  return "D";
}

function isoNow() {
  return new Date().toISOString();
}

// Snapshot storage (local device)
// Keyed by: season|team|week|opp
function snapshotKey(team, season, week, opp) {
  return `oracleSnap|${safeText(season)}|${safeText(team)}|wk${safeText(week)}|${safeText(opp)}`;
}

function saveSnapshot(key, payload) {
  try {
    localStorage.setItem(key, JSON.stringify(payload));
  } catch (e) {
    // ignore storage errors
  }
}

function loadSnapshot(key) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    return JSON.parse(raw);
  } catch (e) {
    return null;
  }
}

function resultFromScoreStr(scoreStr) {
  // Optional: if result missing but score exists like "24-20"
  // You already have g.result, so this is just a fallback.
  if (!scoreStr || typeof scoreStr !== "string") return null;
  const m = scoreStr.match(/(\d+)\s*-\s*(\d+)/);
  if (!m) return null;
  const a = Number(m[1]), b = Number(m[2]);
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  if (a > b) return "W";
  if (a < b) return "L";
  return "T";
}

function pickMatchesResult(pick, result) {
  if (!pick || !result) return null;
  const p = String(pick).toUpperCase();
  const r = String(result).toUpperCase();
  if (p === "NO EDGE" || p === "—") return null;
  if (p === "W" && r === "W") return true;
  if (p === "L" && r === "L") return true;
  if (p === "T" && r === "T") return true;
  return false;
}

// -------------------- UI renderers --------------------
function renderSeasonView() {
  const el = document.getElementById("season");
  if (!DATA || !DATA.games) {
    el.innerHTML = "";
    return;
  }

  const rows = DATA.games.map(g => {
    const res = g.result ?? "TBD";
    const opp = g.opponent ?? "???";
    const wk = g.week ?? "?";
    const score = g.score ?? "";

    const pick = g.oracle?.pregame_pick ?? "—";
    const pwin = g.oracle?.pregame_expected_win_rate;
    const conf = g.oracle?.pregame_confidence;
    const lock = g.oracle?.reality_lock ?? "—";

    // Evidence (n) + grade
    const hm = g.oracle?.pregame_historical_map || {};
    const n = Number.isFinite(hm.n) ? hm.n : 0;
    const grade = evidenceGradeFromN(n);

    // Snapshot indicator (if a snapshot exists for this game)
    const teamCode = DATA?.summary?.team ?? "";
    const season = DATA?.summary?.season ?? "";
    const snap = loadSnapshot(snapshotKey(teamCode, season, wk, opp));
    const snapTag = snap ? `SNAP ${safeText(snap.evidence_grade)} (${safeText(snap.evidence_n)})` : "—";

    return `
      <tr>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${wk}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${opp}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${res}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${safeText(score)}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${pick}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${pwin == null ? "—" : pct(pwin)}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${conf == null ? "—" : Math.round(conf)}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">n=${n} • ${grade}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${lock}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${snapTag}</td>
      </tr>
    `;
  }).join("");

  el.innerHTML = `
    <table style="width:100%; border-collapse:collapse; font-size:14px;">
      <thead>
        <tr style="text-align:left;">
          <th style="padding:6px 8px; border-bottom:2px solid #ddd;">Week</th>
          <th style="padding:6px 8px; border-bottom:2px solid #ddd;">Opp</th>
          <th style="padding:6px 8px; border-bottom:2px solid #ddd;">Result</th>
          <th style="padding:6px 8px; border-bottom:2px solid #ddd;">Score</th>
          <th style="padding:6px 8px; border-bottom:2px solid #ddd;">Pick</th>
          <th style="padding:6px 8px; border-bottom:2px solid #ddd;">Exp W%</th>
          <th style="padding:6px 8px; border-bottom:2px solid #ddd;">Conf</th>
          <th style="padding:6px 8px; border-bottom:2px solid #ddd;">Evidence</th>
          <th style="padding:6px 8px; border-bottom:2px solid #ddd;">Reality</th>
          <th style="padding:6px 8px; border-bottom:2px solid #ddd;">Snapshot</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

/**
 * Next Game Oracle:
 * - Always show a speculative lean (even if n=0 / no fields exist)
 * - Compute Evidence grade from n
 * - Save a local prediction snapshot (per device) so we can later audit match/diverge
 */
function renderNextGame() {
  const box = document.getElementById("nextgame");
  if (!DATA || !DATA.games) {
    box.innerHTML = "";
    return;
  }

  const upcoming = DATA.games
    .filter(g => g.result == null)
    .sort((a, b) => (a.week ?? 999) - (b.week ?? 999));

  const next = upcoming[0];
  if (!next) {
    box.innerHTML = `<div>Season complete (no upcoming games found).</div>`;
    return;
  }

  const teamCode = DATA?.summary?.team ?? "";
  const season = DATA?.summary?.season ?? "";

  const o = next.oracle || {};
  const hm = o.pregame_historical_map || {};
  const n = Number.isFinite(hm.n) ? hm.n : 0;
  const grade = evidenceGradeFromN(n);

  // Always-on speculative defaults:
  const pwin = (o.pregame_expected_win_rate == null) ? 0.50 : o.pregame_expected_win_rate;
  const conf = (o.pregame_confidence == null) ? 0 : o.pregame_confidence;

  const pick =
    (o.pregame_pick != null && o.pregame_pick !== "")
      ? o.pregame_pick
      : (pwin > 0.52 ? "W" : (pwin < 0.48 ? "L" : "No Edge"));

  const confLabel =
    conf >= 75 ? "HIGH" :
    conf >= 60 ? "MED" :
    conf >= 45 ? "LOW" : "VERY LOW";

  // Committed line (optional):
  const committedOk = n > 0 && o.pregame_expected_win_rate != null && o.pregame_confidence != null;
  const committedText = committedOk
    ? `Expected win rate: ${pct(o.pregame_expected_win_rate)} (n=${n}, ${grade}) • Confidence: ${Math.round(o.pregame_confidence)}/100`
    : `Committed call withheld (insufficient similar-history: n=${n}, ${grade}).`;

  // ---- Snapshot: store speculative prediction for this upcoming game ----
  const key = snapshotKey(teamCode, season, next.week, next.opponent);
  const existing = loadSnapshot(key);

  // Only save if we don't already have a snapshot (don’t overwrite history)
  if (!existing) {
    saveSnapshot(key, {
      created_at: isoNow(),
      team: teamCode,
      season,
      week: next.week,
      opponent: next.opponent,
      pick,
      pwin,
      conf,
      evidence_n: n,
      evidence_grade: grade
    });
  }

  const snap = existing || loadSnapshot(key);
  const snapLine = snap
    ? `Snapshot saved: ${safeText(snap.created_at)} • ${safeText(snap.pick)} • ${pct(snap.pwin)} • ${Math.round(snap.conf)}/100 • n=${safeText(snap.evidence_n)} ${safeText(snap.evidence_grade)}`
    : "Snapshot: —";

  box.innerHTML = `
    <div style="font-size:18px; font-weight:700; margin-bottom:6px;">
      Week ${safeText(next.week)} vs ${safeText(next.opponent)} — Upcoming
    </div>

    <div style="margin:8px 0; padding:10px; border-radius:10px; background:#f6f6f6;">
      <div style="font-weight:700; margin-bottom:4px;">Speculative line (always shown)</div>
      <div><b>Lean:</b> ${pick}</div>
      <div><b>Win prob:</b> ${pct(pwin)} • <b>Confidence:</b> ${Math.round(conf)}/100 (${confLabel})</div>
      <div style="color:#444; margin-top:4px;"><b>Evidence:</b> similar-history n=${n} • grade ${grade}</div>
      <div style="color:#444; margin-top:6px; font-size:12px;">${snapLine}</div>
    </div>

    <div style="margin:8px 0; padding:10px; border-radius:10px; border:1px solid #ddd;">
      <div style="font-weight:700; margin-bottom:4px;">Committed Oracle (only when evidence exists)</div>
      <div>${committedText}</div>
    </div>

    <div style="margin-top:10px; color:#333;">${safeText(o.explain_pregame)}</div>
  `;
}

function renderGame(g) {
  document.getElementById("gameout").textContent = JSON.stringify(g, null, 2);

  const oracle = g.oracle || {};
  const coh = oracle.coherence;
  const cohText = coh == null ? "Coherence: —" : `Coherence: ${coh}  ${bars(coh)}  (team internal consistency)`;

  const wlc = oracle.win_loss_coherence;
  const wlcText = wlc == null ? "Win/Loss coherence: —" : `Win/Loss coherence: ${wlc.grade} (${wlc.label})`;

  const lock = oracle.reality_lock ? `Reality lock: ${oracle.reality_lock}` : "Reality lock: —";
  const expl = oracle.explain ?? oracle.explain_pregame ?? "";

  const pick = oracle.pregame_pick ?? "—";
  const pwin = oracle.pregame_expected_win_rate;
  const conf = oracle.pregame_confidence;
  const hm = oracle.pregame_historical_map || {};
  const n = Number.isFinite(hm.n) ? hm.n : 0;
  const grade = evidenceGradeFromN(n);

  const expText = (pwin == null || conf == null)
    ? `Expected win rate: — — Confidence: — • Evidence: n=${n} (${grade})`
    : `Expected win rate: ${pct(pwin)} (n=${n}) — Confidence: ${Math.round(conf)}/100 • Evidence grade ${grade}`;

  // Snapshot compare (if exists)
  const teamCode = DATA?.summary?.team ?? "";
  const season = DATA?.summary?.season ?? "";
  const key = snapshotKey(teamCode, season, g.week, g.opponent);
  const snap = loadSnapshot(key);

  const actualResult = g.result ?? resultFromScoreStr(g.score);
  const snapMatch = snap ? pickMatchesResult(snap.pick, actualResult) : null;

  let snapBlock = "";
  if (snap) {
    const verdict =
      (actualResult == null) ? "Upcoming (no result yet)" :
      (snapMatch === true) ? "MATCH ✅" :
      (snapMatch === false) ? "DIVERGE ❌" :
      "N/A";
    snapBlock = `
      <div style="margin-top:10px; padding:10px; border-radius:10px; border:1px dashed #bbb;">
        <div style="font-weight:700; margin-bottom:6px;">Prediction Snapshot (device-local)</div>
        <div><b>Saved:</b> ${safeText(snap.created_at)}</div>
        <div><b>Pick:</b> ${safeText(snap.pick)} • <b>Win prob:</b> ${pct(snap.pwin)} • <b>Conf:</b> ${Math.round(snap.conf)}/100</div>
        <div><b>Evidence:</b> n=${safeText(snap.evidence_n)} • grade ${safeText(snap.evidence_grade)}</div>
        <div style="margin-top:6px;"><b>Outcome check:</b> ${verdict}</div>
      </div>
    `;
  }

  document.getElementById("read").innerHTML = `
    <div style="font-size:18px; font-weight:700; margin-bottom:6px;">
      Week ${safeText(g.week)} vs ${safeText(g.opponent)} — ${outcomeLabel(g.result)} ${g.score ? `(${g.score})` : ""}
    </div>
    <div style="margin:6px 0;"><b>Pregame pick:</b> ${pick} • ${expText}</div>
    <div style="margin:6px 0;">${cohText}</div>
    <div style="margin:6px 0;">${lock}</div>
    <div style="margin:6px 0;">${wlcText}</div>
    <div style="margin-top:10px; color:#333;">${safeText(expl)}</div>
    ${snapBlock}
  `;
}

// -------------------- data loading --------------------
function populateTeamDropdown() {
  const teamSel = document.getElementById("team");
  teamSel.innerHTML = "";

  TEAMS.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t.key;
    opt.textContent = `${t.team}`;
    teamSel.appendChild(opt);
  });
}

async function loadTeams() {
  const res = await fetch(`./teams.json`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Fetch failed for teams.json (${res.status})`);
  const payload = await res.json();
  TEAMS = (payload.teams || []).slice();

  TEAMS.sort((a, b) => (a.team || "").localeCompare(b.team || ""));
  populateTeamDropdown();
}

async function loadTeam(teamKey) {
  const statusEl = document.getElementById("status");
  statusEl.textContent = "Loading...";

  const res = await fetch(`./${teamKey}.json`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Fetch failed for ${teamKey}.json (${res.status})`);

  DATA = await res.json();
  statusEl.textContent = `Loaded ✅ ${DATA.summary.team} ${DATA.summary.season}`;

  document.getElementById("summary").textContent = JSON.stringify(DATA.summary, null, 2);

  renderSeasonView();
  renderNextGame();

  const sel = document.getElementById("game");
  sel.innerHTML = "";
  DATA.games.forEach((g, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `Week ${g.week} vs ${g.opponent} — ${g.result ?? "TBD"}`;
    sel.appendChild(opt);
  });

  sel.onchange = () => renderGame(DATA.games[Number(sel.value)]);
  renderGame(DATA.games[0]);
}

async function boot() {
  await loadTeams();

  const teamSel = document.getElementById("team");
  const hasGB = TEAMS.find(t => t.key === "gb");
  const defaultKey = hasGB ? "gb" : (TEAMS[0]?.key || "gb");
  teamSel.value = defaultKey;

  teamSel.addEventListener("change", (e) => loadTeam(e.target.value));
  document.getElementById("refresh").addEventListener("click", () => {
    loadTeam(document.getElementById("team").value);
  });

  await loadTeam(defaultKey);
}

boot().catch(err => {
  document.getElementById("status").textContent = "Failed ❌ " + err.message;
});
