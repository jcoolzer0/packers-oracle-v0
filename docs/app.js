let DATA = null;
let TEAMS = null;

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

function wlExpectationFromHist(histNorm) {
  if (!histNorm || !histNorm.n) return null;
  const w = histNorm.W ?? 0;
  const t = histNorm.T ?? 0;
  return w + 0.5 * t;
}

function pickFromPwin(pWin) {
  if (pWin === null || pWin === undefined) return null;
  return pWin >= 0.5 ? "W" : "L";
}

function findNextGameIndex(games) {
  // Next unplayed game = first where result is null/undefined
  const idx = games.findIndex(g => g.result === null || g.result === undefined);
  return idx >= 0 ? idx : 0;
}

function renderNextGame() {
  const box = document.getElementById("nextgame");
  box.textContent = "Loading next game…";

  if (!box) return;

  if (!DATA || !Array.isArray(DATA.games) || DATA.games.length === 0) {
    box.textContent = "No games found.";
    return;
  }

  const idx = findNextGameIndex(DATA.games);
  const g = DATA.games[idx];
  const o = g.oracle || {};

  const pick = o.pregame_pick ?? pickFromPwin(o.pregame_expected_win_rate);
  const pWin = o.pregame_expected_win_rate ?? null;
  const conf = o.pregame_confidence ?? null;
  const hist = o.pregame_historical_map ?? null;

  const expText =
    pWin == null
      ? "Expected win rate: — (Oracle withholds; insufficient similar-history)"
      : `Expected win rate: ${pct(pWin)} (n=${hist?.n ?? "?"})`;

  const confText =
    conf == null
      ? "Confidence: —"
      : `Confidence: ${Math.round(conf)}/100  ${bars(conf)}`;

  const pickText =
    pick == null
      ? "Oracle pick: —"
      : `Oracle pick: ${pick === "W" ? "WIN" : "LOSS"}`;

  const lockText =
    o.reality_lock ? `Reality lock: ${o.reality_lock}` : "Reality lock: —";

  const explain = o.explain_pregame ?? o.explain ?? "";

  // Helpful heading
  const head = `Week ${g.week} vs ${g.opponent} — ${outcomeLabel(g.result)}`;

  box.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:baseline; gap:10px; flex-wrap:wrap;">
      <div style="font-size:18px; font-weight:800;">${head}</div>
      <div style="opacity:0.75;">Next game spotlight</div>
    </div>

    <div style="margin-top:10px; font-weight:700;">${pickText}</div>
    <div style="margin-top:6px;">${expText}</div>
    <div style="margin-top:6px;">${confText}</div>
    <div style="margin-top:6px;">${lockText}</div>

    <div style="margin-top:10px; color:#333; line-height:1.35;">${explain}</div>

    <div style="margin-top:12px; display:flex; gap:10px; flex-wrap:wrap;">
      <button id="jumpNext" style="padding:8px 10px; border-radius:10px; border:1px solid #ccc; cursor:pointer;">
        Jump to this game
      </button>
    </div>
  `;

  const btn = document.getElementById("jumpNext");
  if (btn) {
    btn.onclick = () => {
      const sel = document.getElementById("game");
      if (!sel) return;
      sel.value = String(idx);
      renderGame(DATA.games[idx]);
    };
  }
}

function renderGame(g) {
  document.getElementById("gameout").textContent = JSON.stringify(g, null, 2);

  const oracle = g.oracle || {};

  // Postgame coherence (if game played)
  const coh = oracle.coherence;
  const cohText = coh == null
    ? "Coherence: —"
    : `Coherence: ${coh}  ${bars(coh)}  (postgame: how internally 'clean' the performance looked vs this season)`;

  // Pregame expectation (if present)
  const pWin = oracle.pregame_expected_win_rate ?? null;
  const conf = oracle.pregame_confidence ?? null;
  const hist = oracle.pregame_historical_map ?? null;

  const expText = pWin == null
    ? "Pregame expected win rate: — (Oracle makes no claim yet)"
    : `Pregame expected win rate: ${pct(pWin)} (n=${hist?.n ?? "?"})`;

  const confText = conf == null
    ? "Pregame confidence: —"
    : `Pregame confidence: ${Math.round(conf)}/100  ${bars(conf)}`;

  const pick = oracle.pregame_pick ?? pickFromPwin(pWin);
  const pickText = pick == null
    ? "Pregame pick: —"
    : `Pregame pick: ${pick === "W" ? "WIN" : "LOSS"}`;

  const lock = oracle.reality_lock ? `Reality lock: ${oracle.reality_lock}` : "Reality lock: —";

  // Win/Loss coherence grade (if present)
  const wlc = oracle.win_loss_coherence;
  const wlcText = wlc == null
    ? "Win/Loss coherence: —"
    : `Win/Loss coherence: ${wlc.grade} (${wlc.label})  [predicted: ${wlc.predicted}]`;

  const expl = oracle.explain ?? "";

  document.getElementById("read").innerHTML = `
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
  const res = await fetch(`./${teamKey}.json`, { cache: "no-store" });
  DATA = await res.json();

  // Make app visible (if you are hiding it until data loads)
  const app = document.getElementById("app");
  if (app) app.style.display = "block";

  document.getElementById("status").textContent =
    `Loaded ✅ ${DATA.summary.team} ${DATA.summary.season}`;

  document.getElementById("summary").textContent =
    JSON.stringify(DATA.summary, null, 2);

  // Build game dropdown
  const sel = document.getElementById("game");
  sel.innerHTML = "";
  DATA.games.forEach((g, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `Week ${g.week} vs ${g.opponent} — ${g.result ?? "TBD"}`;
    sel.appendChild(opt);
  });

  sel.onchange = () => renderGame(DATA.games[Number(sel.value)]);

  // Auto spotlight next game + auto-select it
  const nextIdx = findNextGameIndex(DATA.games);
  sel.value = String(nextIdx);

  // ✅ Force Next Game render AFTER dropdown is built and DATA is set
  try { renderNextGame(); } catch (e) { console.error("renderNextGame failed", e); }

  // Render selected game
  renderGame(DATA.games[nextIdx]);

  // ✅ Optional: also re-render next game after the selected game renders
  // (sometimes helps if fonts/layout settle late)
  setTimeout(() => {
    try { renderNextGame(); } catch (e) {}
  }, 0);
}


async function loadTeam(teamKey) {
  const res = await fetch(`./${teamKey}.json`, { cache: "no-store" });
  DATA = await res.json();

  document.getElementById("status").textContent =
    `Loaded ✅ ${DATA.summary.team} ${DATA.summary.season}`;

  document.getElementById("summary").textContent =
    JSON.stringify(DATA.summary, null, 2);

  // Build game dropdown
  const sel = document.getElementById("game");
  sel.innerHTML = "";
  DATA.games.forEach((g, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `Week ${g.week} vs ${g.opponent} — ${g.result ?? "TBD"}`;
    sel.appendChild(opt);
  });

  sel.onchange = () => renderGame(DATA.games[Number(sel.value)]);

  // Auto spotlight next game + auto-select it in dropdown
  const nextIdx = findNextGameIndex(DATA.games);
  sel.value = String(nextIdx);

  renderNextGame();
  renderGame(DATA.games[nextIdx]);
}

// Hook refresh button (manual reload, same team)
function wireRefresh() {
  const btn = document.getElementById("refresh");
  if (!btn) return;
  btn.onclick = () => {
    const teamKey = document.getElementById("team").value;
    loadTeam(teamKey);
  };
}

// Team change handler
document.getElementById("team").addEventListener("change", (e) => loadTeam(e.target.value));

(async function boot() {
  wireRefresh();
  await loadTeams();

  // Default team: gb if present, else first option
  const teamSel = document.getElementById("team");
  const defaultKey = teamSel?.value || "gb";

  loadTeam(defaultKey).catch(err => {
    document.getElementById("status").textContent = "Failed ❌ " + err;
  });
})();
