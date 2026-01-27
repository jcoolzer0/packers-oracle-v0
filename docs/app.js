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

// Keyed by: season|team|week|opp
function snapshotKey(team, season, week, opp) {
  return `oracleSnap|${safeText(season)}|${safeText(team)}|wk${safeText(week)}|${safeText(opp)}`;
}

function saveSnapshot(key, payload) {
  try { localStorage.setItem(key, JSON.stringify(payload)); } catch (e) {}
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

// ---- NEW: alias fallback for team keys (prevents Rams vanishing) ----
const TEAM_KEY_FALLBACKS = {
  "lar": ["la", "LA"],
  "la": ["lar", "LA"],
  "LA": ["lar", "la"],

  // optional extra safety:
  "wsh": ["was"],
  "was": ["wsh"],
};

async function fetchTeamJsonWithFallback(teamKey) {
  const tryKeys = [teamKey].concat(TEAM_KEY_FALLBACKS[teamKey] || []);
  let lastErr = null;

  for (const k of tryKeys) {
    try {
      const res = await fetch(`./${k}.json`, { cache: "no-store" });
      if (!res.ok) throw new Error(`Fetch failed for ${k}.json (${res.status})`);
      const data = await res.json();
      return { data, usedKey: k };
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr || new Error("Fetch failed.");
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

    const hm = g.oracle?.pregame_historical_map || {};
    const n = Number.isFinite(hm.n) ? hm.n : 0;
    const grade = evidenceGradeFromN(n);

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

// (everything else unchanged until loadTeam) ...

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

  // NEW: resilient fetch
  const { data, usedKey } = await fetchTeamJsonWithFallback(teamKey);
  DATA = data;

  statusEl.textContent = `Loaded ✅ ${DATA.summary.team} ${DATA.summary.season} (file: ${usedKey}.json)`;

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
