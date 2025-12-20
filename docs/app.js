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

function outcomeLabel(result) {
  if (result === "W") return "Win";
  if (result === "L") return "Loss";
  if (result === "T") return "Tie";
  return "Upcoming";
}

function renderNextGame() {
  const next = (DATA.games || []).find(g => g.result == null);
  const el = document.getElementById("next");
  if (!el) return;

  if (!next) {
    el.textContent = "No upcoming games found.";
    return;
  }

  const o = next.oracle || {};
  const pick = o.pregame_pick ?? "—";
  const conf = o.pregame_confidence == null ? "—" : `${Math.round(o.pregame_confidence)}/100`;
  const pwin = o.pregame_expected_win_rate == null ? "—" : pct(o.pregame_expected_win_rate);
  const expl = o.explain_pregame ?? "";

  el.innerHTML = `
    <div style="font-size:18px; font-weight:700; margin-bottom:6px;">
      Week ${next.week} vs ${next.opponent} — Upcoming
    </div>
    <div style="margin:6px 0;">Pregame pick: <b>${pick}</b></div>
    <div style="margin:6px 0;">Expected win rate: <b>${pwin}</b></div>
    <div style="margin:6px 0;">Confidence: <b>${conf}</b></div>
    <div style="margin-top:10px; color:#333;">${expl}</div>
  `;
}

function renderSeasonTable() {
  const host = document.getElementById("season");
  if (!host) return;

  const rows = (DATA.games || []).map(g => {
    const o = g.oracle || {};
    const pick = o.pregame_pick ?? "—";
    const conf = o.pregame_confidence == null ? "—" : Math.round(o.pregame_confidence);
    const pwin = o.pregame_expected_win_rate == null ? "—" : Math.round(o.pregame_expected_win_rate * 100);
    const lock = o.reality_lock ?? "—";
    const coh = o.coherence == null ? "—" : Math.round(o.coherence);
    return `
      <tr>
        <td style="padding:6px 8px;">${g.week}</td>
        <td style="padding:6px 8px;">${g.opponent}</td>
        <td style="padding:6px 8px;">${pick}</td>
        <td style="padding:6px 8px;">${pwin === "—" ? "—" : pwin + "%"}</td>
        <td style="padding:6px 8px;">${conf === "—" ? "—" : conf + "/100"}</td>
        <td style="padding:6px 8px;">${g.result ?? "TBD"}</td>
        <td style="padding:6px 8px;">${lock}</td>
        <td style="padding:6px 8px;">${coh}</td>
      </tr>
    `;
  }).join("");

  host.innerHTML = `
    <table style="border-collapse:collapse; width:100%; min-width:760px;">
      <thead>
        <tr style="background:#f6f6f6;">
          <th style="text-align:left; padding:6px 8px;">Wk</th>
          <th style="text-align:left; padding:6px 8px;">Opp</th>
          <th style="text-align:left; padding:6px 8px;">Pick</th>
          <th style="text-align:left; padding:6px 8px;">Exp Win%</th>
          <th style="text-align:left; padding:6px 8px;">Conf</th>
          <th style="text-align:left; padding:6px 8px;">Result</th>
          <th style="text-align:left; padding:6px 8px;">Reality</th>
          <th style="text-align:left; padding:6px 8px;">Coherence</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
  `;
}

function renderGame(g) {
  document.getElementById("gameout").textContent = JSON.stringify(g, null, 2);

  const o = g.oracle || {};
  const pick = o.pregame_pick ?? "—";
  const conf = o.pregame_confidence == null ? "—" : `${Math.round(o.pregame_confidence)}/100`;
  const exp = o.pregame_expected_win_rate == null ? "—" : pct(o.pregame_expected_win_rate);

  const coh = o.coherence;
  const cohText = coh == null ? "Coherence: —" : `Coherence: ${coh}  ${bars(coh)}  (postgame internal consistency)`;

  const wlc = o.win_loss_coherence;
  const wlcText = wlc == null ? "Win/Loss coherence: —" : `Win/Loss coherence: ${wlc.grade} (${wlc.label}; predicted ${wlc.predicted})`;

  const lock = o.reality_lock ? `Reality lock: ${o.reality_lock}` : "Reality lock: —";

  const explPre = o.explain_pregame ?? "";
  const explPost = o.explain ?? "";

  document.getElementById("read").innerHTML = `
    <div style="font-size:18px; font-weight:700; margin-bottom:6px;">
      Week ${g.week} vs ${g.opponent} — ${outcomeLabel(g.result)} ${g.score ? `(${g.score})` : ""}
    </div>
    <div style="margin:6px 0;">Pregame pick: <b>${pick}</b> · Expected win rate: <b>${exp}</b> · Confidence: <b>${conf}</b></div>
    <div style="margin:6px 0;">${cohText}</div>
    <div style="margin:6px 0;">${lock}</div>
    <div style="margin:6px 0;">${wlcText}</div>
    <div style="margin-top:10px; color:#333;"><b>Pregame:</b> ${explPre}</div>
    <div style="margin-top:6px; color:#333;"><b>Postgame:</b> ${explPost}</div>
  `;
}

async function loadTeam(teamKey) {
  const res = await fetch(`./${teamKey}.json`, { cache: "no-store" });
  DATA = await res.json();

  document.getElementById("status").textContent = `Loaded ✅ ${DATA.summary.team} ${DATA.summary.season}`;
  document.getElementById("summary").textContent = JSON.stringify(DATA.summary, null, 2);

  const sel = document.getElementById("game");
  sel.innerHTML = "";

  (DATA.games || []).forEach((g, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `Week ${g.week} vs ${g.opponent} — ${g.result ?? "TBD"}`;
    sel.appendChild(opt);
  });

  sel.onchange = () => renderGame(DATA.games[Number(sel.value)]);

  renderNextGame();
  renderSeasonTable();
  renderGame(DATA.games[0]);
}

async function loadTeamsDropdown() {
  const teamSelect = document.getElementById("team");
  if (!teamSelect) return;

  // If teams.json exists, populate dropdown with all teams.
  try {
    const res = await fetch("./teams.json", { cache: "no-store" });
    const t = await res.json();
    if (t && Array.isArray(t.teams)) {
      teamSelect.innerHTML = "";
      t.teams.forEach(x => {
        const opt = document.createElement("option");
        opt.value = x.key;
        opt.textContent = `${x.team} (${x.team})`;
        teamSelect.appendChild(opt);
      });
    }
  } catch (_) {
    // fallback: keep existing static options
  }
}

// Wire UI events once
document.getElementById("team").addEventListener("change", (e) => loadTeam(e.target.value));
document.getElementById("refresh").addEventListener("click", () => {
  const teamKey = document.getElementById("team").value;
  loadTeam(teamKey);
});

// Init
(async () => {
  await loadTeamsDropdown();

  // Prefer GB if present
  const teamSelect = document.getElementById("team");
  const preferred = (teamSelect && [...teamSelect.options].some(o => o.value === "gb")) ? "gb" : teamSelect.value;

  await loadTeam(preferred);
})().catch(err => {
  document.getElementById("status").textContent = "Failed ❌ " + err;
});
