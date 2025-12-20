// Simple shared passcode gate (privacy-by-link).
// NOTE: This is NOT high-security; passcode is in client JS (inspectable).
// Good for friends/family demos where you don't want casual public browsing.

(function () {
  const PASSCODE = "oraclefootball";
  const KEY = "oracle_football_authed_v1";

  function lockScreen() {
    document.body.innerHTML = `
      <div style="font-family:system-ui; max-width:520px; margin:70px auto; padding:0 16px;">
        <h1 style="margin-bottom:8px;">Oracle Football</h1>
        <p style="margin-top:0; color:#444;">Enter passcode to continue.</p>
        <input id="pw" type="password" placeholder="Passcode"
               style="font-size:16px; padding:10px 12px; width:100%; border:1px solid #ccc; border-radius:10px;" />
        <button id="go"
                style="margin-top:10px; font-size:16px; padding:10px 12px; border:0; border-radius:10px; cursor:pointer;">
          Unlock
        </button>
        <p id="msg" style="color:#b00020; min-height:20px;"></p>
      </div>
    `;

    const pw = document.getElementById("pw");
    const go = document.getElementById("go");
    const msg = document.getElementById("msg");

    function tryUnlock() {
      const v = (pw.value || "").trim();
      if (v === PASSCODE) {
        localStorage.setItem(KEY, "1");
        location.reload();
      } else {
        msg.textContent = "Nope — try again.";
        pw.select();
      }
    }

    go.onclick = tryUnlock;
    pw.addEventListener("keydown", (e) => {
      if (e.key === "Enter") tryUnlock();
    });
    pw.focus();
  }

  function unlockApp() {
    const app = document.getElementById("app");
    if (app) app.style.display = "block";
  }

  // If already authed, show app. Otherwise show lock screen.
  if (localStorage.getItem(KEY) === "1") {
    unlockApp();
  } else {
    lockScreen();
  }

  // Optional: allow logout by appending ?logout=1 to URL
  const params = new URLSearchParams(location.search);
  if (params.get("logout") === "1") {
    localStorage.removeItem(KEY);
    location.href = location.pathname;
  }
})();

