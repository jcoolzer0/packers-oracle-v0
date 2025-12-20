let DATA = null;
let TEAMS = [];

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

    return `
      <tr>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${wk}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${opp}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${res}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${safeText(score)}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${pick}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${pwin == null ? "—" : pct(pwin)}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${conf == null ? "—" : Math.round(conf)}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${lock}</td>
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
          <th style="padding:6px 8px; border-bottom:2px solid #ddd;">Reality</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderNextGame() {
  const box = document.getElementById("nextgame");
  if (!DATA || !DATA.games) {
    box.innerHTML = "";
    return;
  }

  const next = DATA.games.find(g => g.result == null);
  if (!next) {
    box.innerHTML = `<div>Season complete (no upcoming games found).</div>`;
    return;
  }

  const o = next.oracle || {};
  const pick = o.pregame_pick ?? "—";
  const pwin = o.pregame_expected_win_rate;
  const conf = o.pregame_confidence;
  const hm = o.pregame_historical_map;

  const expText = (pwin == null || !hm?.n)
    ? "Oracle has insufficient similar-history; it withholds a win/loss confidence."
    : `Expected win rate: ${pct(pwin)} (n=${hm.n}) • Confidence: ${Math.round(conf)}/100`;

  box.innerHTML = `
    <div style="font-size:18px; font-weight:700; margin-bottom:6px;">
      Week ${next.week} vs ${next.opponent} — Upcoming
    </div>
    <div style="margin:6px 0;"><b>Pregame pick:</b> ${pick}</div>
    <div style="margin:6px 0;">${expText}</div>
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
  const hm = oracle.pregame_historical_map;

  const expText = (pwin == null || conf == null || !hm?.n)
    ? "Expected win rate: — — Confidence: —"
    : `Expected win rate: ${pct(pwin)} (n=${hm.n}) — Confidence: ${Math.round(conf)}/100`;

  document.getElementById("read").innerHTML = `
    <div style="font-size:18px; font-weight:700; margin-bottom:6px;">
      Week ${g.week} vs ${g.opponent} — ${outcomeLabel(g.result)} ${g.score ? `(${g.score})` : ""}
    </div>
    <div style="margin:6px 0;"><b>Pregame pick:</b> ${pick} • ${expText}</div>
    <div style="margin:6px 0;">${cohText}</div>
    <div style="margin:6px 0;">${lock}</div>
    <div style="margin:6px 0;">${wlcText}</div>
    <div style="margin-top:10px; color:#333;">${safeText(expl)}</div>
  `;
}

function populateTeamDropdown() {
  const teamSel = document.getElementById("team");
  teamSel.innerHTML = "";

  TEAMS.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t.key;                  // e.g. "gb", "phi", "sf", etc.
    opt.textContent = `${t.team}`;      // e.g. "GB"
    teamSel.appendChild(opt);
  });
}

async function loadTeams() {
  const res = await fetch(`./teams.json`, { cache: "no-store" });
  if (!res.ok) throw new Error(`Fetch failed for teams.json (${res.status})`);
  const payload = await res.json();
  TEAMS = (payload.teams || []).slice();

  // Nice: sort alphabetically by team code
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
  // 1) load teams list
  await loadTeams();

  // 2) pick default (try GB if present)
  const teamSel = document.getElementById("team");
  const hasGB = TEAMS.find(t => t.key === "gb");
  const defaultKey = hasGB ? "gb" : (TEAMS[0]?.key || "gb");
  teamSel.value = defaultKey;

  // 3) wire controls
  teamSel.addEventListener("change", (e) => loadTeam(e.target.value));
  document.getElementById("refresh").addEventListener("click", () => {
    loadTeam(document.getElementById("team").value);
  });

  // 4) load initial team
  await loadTeam(defaultKey);
}

// Boot
boot().catch(err => {
  document.getElementById("status").textContent = "Failed ❌ " + err.message;
});
