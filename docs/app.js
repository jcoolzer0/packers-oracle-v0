let DATA = null;

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
      Tip: “Pick/Exp/Conf” are pregame (if Oracle has enough similar-history). “Reality/Coh” become meaningful after the game.
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
    pick
