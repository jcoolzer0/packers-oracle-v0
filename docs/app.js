let DATA = null;

function pct(x) {
  if (x === null || x === undefined) return "—";
  return Math.round(x * 100) + "%";
}

function bars(score) {
  if (score === null || score === undefined) return "—";
  const n = Math.max(0, Math.min(5, Math.round(score / 20)));
  return "▮".repeat(n) + "▯".repeat(5 - n);
}

function wlExpectation(oracle) {
  const hm = oracle?.historical_map;
  if (!hm || !hm.n) return null;
  const w = hm.W ?? 0;
  const t = hm.T ?? 0;
  return w + 0.5 * t;
}

function outcomeLabel(result) {
  if (result === "W") return "Win";
  if (result === "L") return "Loss";
  if (result === "T") return "Tie";
  return "Upcoming";
}

function renderGame(g) {
  document.getElementById("gameout").textContent = JSON.stringify(g, null, 2);

  const oracle = g.oracle || {};
  const exp = wlExpectation(oracle);
  const expText =
    exp === null
      ? "No similar-history yet (Oracle makes no claim)."
      : `Expected win rate in similar states: ${pct(exp)} (n=${oracle.historical_map.n})`;

  const coh = oracle.coherence;
  const cohText =
    coh == null
      ? "Coherence: —"
      : `Coherence: ${coh}  ${bars(coh)}  (internal consistency of performance)`;

  const wlc = oracle.win_loss_coherence;
  const wlcText =
    wlc == null
      ? "Win/Loss coherence: —"
      : `Win/Loss coherence: ${wlc.grade} (${wlc.label})`;

  const lock = oracle.reality_lock ? `Reality lock: ${oracle.reality_lock}` : "Reality lock: —";
  const expl = oracle.explain ?? "";

  document.getElementById("read").innerHTML = `
    <div style="font-size:18px; font-weight:700; margin-bottom:6px;">
      Week ${g.week} vs ${g.opponent} — ${outcomeLabel(g.result)} ${g.score ? `(${g.score})` : ""}
    </div>
    <div style="margin:6px 0;">${cohText}</div>
    <div style="margin:6px 0;">${expText}</div>
    <div style="margin:6px 0;">${lock}</div>
    <div style="margin:6px 0;">${wlcText}</div>
    <div style="margin-top:10px; color:#333;">${expl}</div>
  `;
}

async function loadTeam(teamKey) {
  const res = await fetch(`./${teamKey}.json`, { cache: "no-store" });
  DATA = await res.json();

  document.getElementById("status").textContent = `Loaded ✅ ${DATA.summary.team} ${DATA.summary.season}`;
  document.getElementById("summary").textContent = JSON.stringify(DATA.summary, null, 2);

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

// Wire UI events once
document.getElementById("team").addEventListener("change", (e) => loadTeam(e.target.value));
document.getElementById("refresh").addEventListener("click", () => {
  const teamKey = document.getElementById("team").value;
  loadTeam(teamKey);
});

// Initial load
loadTeam("gb").catch(err => {
  document.getElementById("status").textContent = "Failed ❌ " + err;
});
