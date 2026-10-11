let DATA = null;
let TEAMS = [];
const TEAM_KEY_FALLBACKS = { lar: ['la', 'LA'], la: ['lar', 'LA'], wsh: ['was'], was: ['wsh'] };

async function fetchTeamJsonWithFallback(key) {
  let lastError;
  for (const candidate of [key, ...(TEAM_KEY_FALLBACKS[key] || [])]) {
    const response = await fetch(`./${candidate}.json`, { cache: 'no-store' });
    if (response.ok) return { data: await response.json(), usedKey: candidate };
    lastError = new Error(`${candidate}.json: HTTP ${response.status}`);
  }
  throw lastError;
}

function safeText(value) {
  return value === null || value === undefined ? '—' : String(value);
}

function renderSeasonView() {
  const container = document.getElementById('season');
  container.replaceChildren();
  const table = document.createElement('table');
  table.style.cssText = 'width:100%; border-collapse:collapse;';
  const header = table.createTHead().insertRow();
  for (const label of ['Week', 'Date', 'Opponent', 'Venue', 'Result', 'Score', 'Pass yards', 'Rush yards', 'Def sacks']) {
    const cell = document.createElement('th');
    cell.textContent = label;
    header.appendChild(cell);
  }
  const body = table.createTBody();
  for (const game of DATA.games) {
    const row = body.insertRow();
    const stats = game.statistics;
    for (const value of [game.week, game.gameday, game.opponent, game.is_home ? 'Home' : 'Away',
                         game.result || 'Scheduled', game.score, stats?.passing_yards, stats?.rushing_yards, stats?.def_sacks]) {
      row.insertCell().textContent = safeText(value);
    }
  }
  container.appendChild(table);
}

function renderGame(game) {
  document.getElementById('gameout').textContent = JSON.stringify(game, null, 2);
}

let requestId = 0;
async function loadTeam(key) {
  const current = ++requestId;
  const status = document.getElementById('status');
  status.textContent = 'Loading…';
  const { data } = await fetchTeamJsonWithFallback(key);
  if (current !== requestId) return;
  DATA = data;
  status.textContent = `Loaded ${data.summary.team} • ${data.summary.season} regular season`;
  document.getElementById('summary').textContent = JSON.stringify(data.summary, null, 2);
  document.getElementById('read').textContent = JSON.stringify({ statistics: data.statistics, defense_allowed: data.defense_allowed }, null, 2);
  renderSeasonView();
  const next = data.games.find(game => game.result === null);
  document.getElementById('nextgame').textContent = next
    ? `Week ${next.week} • ${safeText(next.gameday)} • ${next.is_home ? 'vs' : 'at'} ${next.opponent}`
    : 'Regular season complete.';
  const gameSelect = document.getElementById('game');
  gameSelect.replaceChildren();
  data.games.forEach((game, index) => {
    const option = document.createElement('option');
    option.value = index;
    option.textContent = `Week ${game.week} vs ${game.opponent}`;
    gameSelect.appendChild(option);
  });
  gameSelect.onchange = () => renderGame(DATA.games[Number(gameSelect.value)]);
  renderGame(data.games[0]);
}

function showError(error) {
  document.getElementById('status').textContent = `Collection data unavailable: ${error.message}`;
}

async function boot() {
  // gate.js removes the app while locked; wait for its reload after unlocking.
  if (!document.getElementById('app')) return;
  const response = await fetch('./teams.json', { cache: 'no-store' });
  if (!response.ok) throw new Error(`teams.json: HTTP ${response.status}`);
  const payload = await response.json();
  TEAMS = payload.teams;
  const select = document.getElementById('team');
  for (const team of TEAMS) {
    const option = document.createElement('option');
    option.value = team.key;
    option.textContent = team.team;
    select.appendChild(option);
  }
  const defaultKey = TEAMS.find(team => team.team === 'GB')?.key || TEAMS[0]?.key;
  select.value = defaultKey;
  select.addEventListener('change', () => loadTeam(select.value).catch(showError));
  document.getElementById('refresh').addEventListener('click', () => loadTeam(select.value).catch(showError));
  const manifestResponse = await fetch('./manifest.json', { cache: 'no-store' });
  if (!manifestResponse.ok) throw new Error(`manifest.json: HTTP ${manifestResponse.status}`);
  const manifest = await manifestResponse.json();
  document.getElementById('coverage').textContent = `${manifest.season} • ${manifest.team_count} teams • ${manifest.schedule_games} games • ${manifest.completed_games} final • statistics ${manifest.statistics_status} • collected ${manifest.collected_at}`;
  await loadTeam(defaultKey);
}

boot().catch(showError);
