// Buffers activity in extension storage and sends it to the local app whenever it's running.
const API = "http://127.0.0.1:8765/api/activity";
let flushing = false;

browser.runtime.onMessage.addListener(async ({ host, day, seconds }) => {
  const { pending = {} } = await browser.storage.local.get("pending");
  pending[host] = pending[host] || {};
  pending[host][day] = (pending[host][day] || 0) + seconds;
  await browser.storage.local.set({ pending });
  flush();
});

async function flush() {
  if (flushing) return;
  flushing = true;
  try {
    const { pending = {} } = await browser.storage.local.get("pending");
    for (const host of Object.keys(pending)) {
      const r = await fetch(API, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ host, days: pending[host] }),
      });
      if (!r.ok) break;
      // remove only what we sent; new seconds may have arrived meanwhile
      const { pending: now = {} } = await browser.storage.local.get("pending");
      for (const [day, s] of Object.entries(pending[host])) {
        now[host][day] -= s;
        if (now[host][day] <= 0) delete now[host][day];
      }
      if (!Object.keys(now[host]).length) delete now[host];
      await browser.storage.local.set({ pending: now });
    }
  } catch (e) {
    // app not running; keep buffered and retry later
  } finally {
    flushing = false;
  }
}

setInterval(flush, 60000);
flush();
