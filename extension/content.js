// Counts seconds this page is visible, focused, and you've typed within the last 30s.
const IDLE_MS = 30000;
let lastKey = 0, pending = 0;
addEventListener("keydown", () => { lastKey = Date.now(); }, true);

setInterval(() => {
  if (document.visibilityState === "visible" && document.hasFocus() && Date.now() - lastKey < IDLE_MS) {
    pending++;
  }
}, 1000);

setInterval(() => {
  if (!pending) return;
  const d = new Date();
  const day = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  browser.runtime.sendMessage({ host: location.hostname, day, seconds: pending });
  pending = 0;
}, 15000);
