let DATA = null;
let TEAMS = null;

function $(id) { return document.getElementById(id); }

function setStatus(msg) {
  const el = $("status");
  if (el) el.textContent = msg;
}

function pct(x) {
  if (x === null || x === undefined) return "—";
  return Math.round(x * 100) + "%";
}

function bars(score) {
  if (score === null || score === undefined) return "—";
  const n = Math.max(0, Math.min(5, Math.round(score / 20)));
  return "▮".repeat(n) + "▯".repeat(5 - n);
}

function outcomeLabel(result) {
  if (result === "W") return "Win";
  if (result === "L") return "Loss";
  if (result === "T") return "Tie";
  return "Upcoming";
}

function pickFromPwin(pWin) {
  if (pWin === null || pWin === undefined) return null;
  return pWin >= 0.5 ? "W" : "L";
}

function findNextGameIndex(games) {
  const idx = games.findIndex(g => g.result === null || g.result === undefined);
  return idx >= 0 ? idx : 0;
}

function teamLabel(t) {
  // teams.json items look like: { team: "GB", key: "gb" }
  const code = (t.team || "").toUpperCase();
  return `${code} (${code})`;
}

async function loadTeams() {
  // expects docs/teams.json
  const res = await fetch("./teams.json", { cache: "no-store" });
  TEAMS = await res.json();
  return TEAMS;
}

function populateTeamDropdown(selectedKey) {
  const sel = $("team");
  if (!sel) return;

  sel.innerHTML = "";

  const list = (TEAMS && TEAMS.teams) ? TEAMS.teams : [
    { team: "GB", key: "gb" },
    { team: "PHI", key: "phi" }
  ];

  list.forEach(t => {
    const opt = document.createElement("option");
    opt.value = t.key;
    opt.textContent = teamLabel(t);
    sel.appendChild(opt);
  });

  if (selectedKey) sel.value = selectedKey;
  if (!sel.value && sel.options.length) sel.value = sel.options[0].value;
}

function renderSeasonTable() {
  const box = $("season");
  if (!box) return;

  if (!DATA || !Array.isArray(DATA.games)) {
    box.innerHTML = `<div style="padding:12px; opacity:.75;">No season data loaded yet.</div>`;
    return;
  }

  const rows = DATA.games.map((g) => {
    const o = g.oracle || {};
    const pWin = o.pregame_expected_win_rate ?? null;
    const conf = o.pregame_confidence ?? null;
    const pick = o.pregame_pick ?? pickFromPwin(pWin);

    const pickTxt = pick == null ? "—" : (pick === "W" ? "WIN" : "LOSS");
    const expTxt  = pWin == null ? "—" : pct(pWin);
    const confTxt = conf == null ? "—" : `${Math.round(conf)}/100`;
    const resTxt  = g.result ?? "TBD";

    const lock = o.reality_lock ?? "—";
    const coh  = o.coherence ?? "—";

    return `
      <tr>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${g.week}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${g.opponent}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${pickTxt}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${expTxt}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${confTxt}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${resTxt}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${lock}</td>
        <td style="padding:6px 8px; border-bottom:1px solid #eee;">${coh}</td>
      </tr>
    `;
  }).join("");

  box.innerHTML = `
    <table style="width:100%; border-collapse:collapse; font-size:14px;">
      <thead>
        <tr>
          <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Week</th>
          <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Opp</th>
          <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Pick</th>
          <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Exp Win%</th>
          <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Conf</th>
          <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Result</th>
          <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Reality</th>
          <th style="text-align:left; padding:8px; border-bottom:1px solid #ddd;">Coh</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    <div style="padding:10px 12px; font-size:12px; opacity:.7;">
      Pick/Exp/Conf are pregame (if enough similar-history exists). Reality/Coh are postgame signals.
    </div>
  `;
}

function renderNextGame() {
  const box = $("nextgame");
  if (!box) return;

  box.innerHTML = `<div style="opacity:.75;">Loading next game…</div>`;

  if (!DATA || !Array.isArray(DATA.games) || DATA.games.length === 0) {
    box.innerHTML = "No games found.";
    return;
  }

  const idx = findNextGameIndex(DATA.games);
  const g = DATA.games[idx];
  const o = g.oracle || {};

  const pWin = o.pregame_expected_win_rate ?? null;
  const conf = o.pregame_confidence ?? null;
  const hist = o.pregame_historical_map ?? null;
  const pick = o.pregame_pick ?? pickFromPwin(pWin);

  const expText =
    pWin == null
      ? "Expected win rate: — (withholding; insufficient similar-history)"
      : `Expected win rate: ${pct(pWin)} (n=${hist?.n ?? "?"})`;

  const confText =
    conf == null
      ? "Confidence: —"
      : `Confidence: ${Math.round(conf)}/100  ${bars(conf)}`;

  const pickText =
    pick == null
      ? "Oracle pick: —"
      : `Oracle pick: ${pick === "W" ? "WIN" : "LOSS"}`;

  const explain = o.explain_pregame ?? o.explain ?? "";

  box.innerHTML = `
    <div style="font-size:18px; font-weight:800; margin-bottom:6px;">
      Week ${g.week} vs ${g.opponent} — ${outcomeLabel(g.result)}
    </div>
    <div style="margin:6px 0; font-weight:700;">${pickText}</div>
    <div style="margin:6px 0;">${expText}</div>
    <div style="margin:6px 0;">${confText}</div>
    <div style="margin-top:10px; color:#333; line-height:1.35;">${explain}</div>
    <div style="margin-top:12px;">
      <button id="jumpNext" style="padding:8px 10px; border-radius:10px; border:1px solid #ccc; cursor:pointer;">
        Jump to this game
      </button>
    </div>
  `;

  const btn = $("jumpNext");
  if (btn) {
    btn.onclick = () => {
      const sel = $("game");
      if (!sel) return;
      sel.value = String(idx);
      renderGame(DATA.games[idx]);
    };
  }
}

function renderGame(g) {
  const out = $("gameout");
  if (out) out.textContent = JSON.stringify(g, null, 2);

  const oracle = g.oracle || {};

  const pWin = oracle.pregame_expected_win_rate ?? null;
  const conf = oracle.pregame_confidence ?? null;
  const hist = oracle.pregame_historical_map ?? null;
  const pick = oracle.pregame_pick ?? pickFromPwin(pWin);

  const expText = pWin == null
    ? "Pregame expected win rate: —"
    : `Pregame expected win rate: ${pct(pWin)} (n=${hist?.n ?? "?"})`;

  const confText = conf == null
    ? "Pregame confidence: —"
    : `Pregame confidence: ${Math.round(conf)}/100  ${bars(conf)}`;

  const pickText = pick == null
    ? "Pregame pick: —"
    : `Pregame pick: ${pick === "W" ? "WIN" : "LOSS"}`;

  const coh = oracle.coherence;
  const cohText = coh == null
    ? "Coherence: —"
    : `Coherence: ${coh}  ${bars(coh)}`;

  const lock = oracle.reality_lock ? `Reality lock: ${oracle.reality_lock}` : "Reality lock: —";

  const wlc = oracle.win_loss_coherence;
  const wlcText = wlc == null
    ? "Win/Loss coherence: —"
    : `Win/Loss coherence: ${wlc.grade} (${wlc.label}) [predicted: ${wlc.predicted}]`;

  const expl = oracle.explain ?? "";

  const read = $("read");
  if (!read) return;

  read.innerHTML = `
    <div style="font-size:18px; font-weight:800; margin-bottom:6px;">
      Week ${g.week} vs ${g.opponent} — ${outcomeLabel(g.result)} ${g.score ? `(${g.score})` : ""}
    </div>

    <div style="margin:6px 0; font-weight:700;">${pickText}</div>
    <div style="margin:6px 0;">${expText}</div>
    <div style="margin:6px 0;">${confText}</div>

    <hr style="border:none; border-top:1px solid #eee; margin:10px 0;" />

    <div style="margin:6px 0;">${cohText}</div>
    <div style="margin:6px 0;">${lock}</div>
    <div style="margin:6px 0;">${wlcText}</div>

    <div style="margin-top:10px; color:#333; line-height:1.35;">${expl}</div>
  `;
}

async function loadTeam(teamKey) {
  setStatus("Loading…");

  const res = await fetch(`./${teamKey}.json`, { cache: "no-store" });
  DATA = await res.json();

  $("app").style.display = "block";
  setStatus(`Loaded ✅ ${DATA.summary.team} ${DATA.summary.season}`);

  $("summary").textContent = JSON.stringify(DATA.summary, null, 2);

  // build game dropdown
  const sel = $("game");
  sel.innerHTML = "";
  DATA.games.forEach((g, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `Week ${g.week} vs ${g.opponent} — ${g.result ?? "TBD"}`;
    sel.appendChild(opt);
  });

  sel.onchange = () => renderGame(DATA.games[Number(sel.value)]);

  const nextIdx = findNextGameIndex(DATA.games);
  sel.value = String(nextIdx);

  renderSeasonTable();
  renderNextGame();
  renderGame(DATA.games[nextIdx]);
}

function showError(err) {
  console.error(err);
  setStatus("Failed ❌ " + (err?.message || err));
  const box = $("nextgame");
  if (box) box.innerHTML = `<b style="color:#b00;">Error:</b> ${String(err?.message || err)}`;
}

(async function boot() {
  try {
    await loadTeams();
  } catch (e) {
    // fallback is okay
    TEAMS = null;
  }

  // Populate dropdown from teams.json (or fallback)
  populateTeamDropdown("gb");

  // Refresh button
  const btn = $("refresh");
  if (btn) {
    btn.onclick = () => loadTeam($("team").value).catch(showError);
  }

  // Changing team loads new JSON
  $("team").addEventListener("change", (e) => {
    loadTeam(e.target.value).catch(showError);
  });

  // Initial load
  loadTeam($("team").value || "gb").catch(showError);
})();
