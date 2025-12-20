async function main() {
  const res = await fetch("./data.json", { cache: "no-store" });
  const data = await res.json();

  document.getElementById("status").textContent = "Loaded ✅";

  document.getElementById("summary").textContent =
    JSON.stringify(data.summary, null, 2);

  const sel = document.getElementById("game");
  data.games.forEach((g, i) => {
    const opt = document.createElement("option");
    opt.value = i;
    opt.textContent = `Week ${g.week} vs ${g.opponent} — ${g.result ?? "TBD"}`;
    sel.appendChild(opt);
  });

  function render(i) {
    document.getElementById("gameout").textContent =
      JSON.stringify(data.games[i], null, 2);
  }

  sel.addEventListener("change", () => render(Number(sel.value)));
  render(0);
}

main().catch(err => {
  document.getElementById("status").textContent = "Failed ❌ " + err;
});

