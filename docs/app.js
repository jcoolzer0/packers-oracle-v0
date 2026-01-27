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

// Snapshot storage
function snapshotKey(team, season, week, opp) {
  return `oracleSnap|${safeText(season)}|${safeText(team)}|wk${safeText(week)}|${safeText(opp)}`;
}

function saveSnapshot(key, payload) {
  try { localStorage.setItem(key, JSON.stringify(payload)); } catch {}
}

function loadSnapshot(key) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

// -------------------- Rams + alias fallback --------------------
const TEAM_KEY_FALLBACKS = {
  "lar": ["la", "LA"],
  "la": ["lar", "LA"],
  "LA": ["lar", "la"],
  "wsh": ["was"],
  "was": ["wsh"],
};

async function fetchTeamJsonWithFallback(teamKey) {
  const keys = [teamKey].concat(TEAM_KEY_FALLBACKS[teamKey] || []);
  let lastErr = null;

  for (const k of keys) {
    try {
      const res = await fetch(`./${k}.json`, { cache: "no-store" });
      if (!res.ok) throw new Error(`Fetch failed for ${k}.json (${res.status})`);
      return { data: await res.json(), usedKey: k };
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr || new Error("All team fetches failed");
}

// -------------------- UI renderers --------------------
function populateTeamDropdown() {
  const sel = document.getElementById("team");
  sel.innerHTML = "";
  TEAMS.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t.key;
    opt.textContent = t.team;
    sel.appendChild(opt);
  });
}

function renderSeasonView() {
  const el = document.getElementById("season");
  if (!DATA || !DATA.games) {
    el.innerHTML = "";
    return;
  }

  const rows = DATA.games.map(g => {
    const hm = g.oracle?.pregame_historical_map || {};
    const n = Number.isFinite(hm.n) ? hm.n : 0;

    return `
      <tr>
        <td>${g.week}</td>
        <td>${safeText(g.opponent)}</td>
        <td>${outcomeLabel(g.result)}</td>
        <td>${safeText(g.score)}</td>
        <td>${safeText(g.oracle?.pregame_pick)}</td>
        <td>${pct(g.oracle?.pregame_expected_win_rate)}</td>
        <td>${safeText(g.oracle?.pregame_confidence)}</td>
        <td>n=${n} • ${evidenceGradeFromN(n)}</td>
        <td>${safeText(g.oracle?.reality_lock)}</td>
      </tr>
    `;
  }).join("");

  el.innerHTML = `
    <table style="width:100%; border-collapse:collapse;">
      <thead>
        <tr>
          <th>Week</th><th>Opp</th><th>Result</th><th>Score</th>
          <th>Pick</th><th>Exp</th><th>Conf</th><th>Evidence</th><th>Reality</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderNextGame() {
  const box = document.getElementById("nextgame");
  if (!DATA || !DATA.games) return;

  const next = DATA.games.find(g => g.result == null);
  if (!next) {
    box.innerHTML = "Season complete.";
    return;
  }

  const o = next.oracle || {};
  const pwin = o.pregame_expected_win_rate ?? 0.5;
  const conf = o.pregame_confidence ?? 0;
  const pick = o.pregame_pick ?? (pwin > 0.52 ? "W" : pwin < 0.48 ? "L" : "No Edge");

  box.innerHTML = `
    <b>Week ${next.week} vs ${next.opponent}</b><br>
    Lean: ${pick}<br>
    Win prob: ${pct(pwin)}<br>
    Confidence: ${Math.round(conf)}/100
  `;
}

function renderGame(g) {
  document.getElementById("gameout").textContent =
    JSON.stringify(g, null, 2);
}

// -------------------- loaders --------------------
async function loadTeams() {
  const res = await fetch("./teams.json", { cache: "no-store" });
  if (!res.ok) throw new Error("teams.json failed");
  const payload = await res.json();
  TEAMS = payload.teams || [];
  populateTeamDropdown();
}

async function loadTeam(teamKey) {
  const status = document.getElementById("status");
  status.textContent = "Loading…";

  const { data, usedKey } = await fetchTeamJsonWithFallback(teamKey);
  DATA = data;

  status.textContent = `Loaded ${DATA.summary.team} (${usedKey}.json)`;

  document.getElementById("summary").textContent =
    JSON.stringify(DATA.summary, null, 2);

  renderSeasonView();
  renderNextGame();

  const gameSel = document.getElementById("game");
  gameSel.innerHTML = "";
  DATA.games.forEach((g, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `Week ${g.week} vs ${g.opponent}`;
    gameSel.appendChild(opt);
  });

  gameSel.onchange = () => renderGame(DATA.games[gameSel.value]);
  renderGame(DATA.games[0]);
}

// -------------------- BOOT (THIS WAS MISSING) --------------------
async function boot() {
  await loadTeams();

  const teamSel = document.getElementById("team");
  const defaultKey = TEAMS[0]?.key;
  teamSel.value = defaultKey;

  teamSel.addEventListener("change", e => loadTeam(e.target.value));
  document.getElementById("refresh")
    .addEventListener("click", () => loadTeam(teamSel.value));

  await loadTeam(defaultKey);
}

boot().catch(err => {
  console.error(err);
  document.getElementById("status").textContent = "Failed ❌ " + err.message;
});
