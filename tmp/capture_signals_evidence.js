const { chromium } = require("../frontend/node_modules/playwright");
const fs = require("fs");

const URL = "http://localhost:3000";
const OUT_JSON = "tmp/signals_evidence.json";
const OUT_TXT = "tmp/signals_stacks.txt";

function nowIso() {
  return new Date().toISOString();
}

const signalsRequests = [];
const consoleLines = [];

(async () => {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  page.on("console", (msg) => {
    const line = `[${nowIso()}] [${msg.type()}] ${msg.text()}`;
    consoleLines.push(line);
  });

  page.on("request", (req) => {
    const url = req.url();
    if (url.includes("/api/signals")) {
      signalsRequests.push({
        ts: nowIso(),
        method: req.method(),
        url,
      });
    }
  });

  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: 60000 });

  await page.screenshot({ path: "tmp/pw_0s.png", fullPage: true });

  await page.waitForTimeout(5000);
  await page.screenshot({ path: "tmp/pw_5s.png", fullPage: true });

  await page.waitForTimeout(5000);
  await page.screenshot({ path: "tmp/pw_10s.png", fullPage: true });

  // Attempt to read signals http store
  let algoEntries = [];
  let stackPrint = "";

  try {
    algoEntries = await page.evaluate(() => {
      if (!window.__SIGNALS_HTTP__) return { error: "window.__SIGNALS_HTTP__ missing" };
      return window.__SIGNALS_HTTP__.filter((x) => x.symbol === "ALGO_USDT");
    });
  } catch (e) {
    algoEntries = { error: String(e) };
  }

  try {
    stackPrint = await page.evaluate(() => {
      if (!window.__PRINT_SIGNALS_STACKS__) return "window.__PRINT_SIGNALS_STACKS__ missing";
      // Capture printed output by returning grouped entries
      // If helper prints to console only, we also attempt to return raw stored stacks
      try { window.__PRINT_SIGNALS_STACKS__(); } catch {}
      if (window.__SIGNALS_HTTP__) {
        const by = {};
        for (const x of window.__SIGNALS_HTTP__) {
          if (!by[x.symbol]) by[x.symbol] = [];
          by[x.symbol].push({ ts: x.t, rid: x.rid, stack: x.stack || "" });
        }
        return JSON.stringify(by, null, 2);
      }
      return "No __SIGNALS_HTTP__ storage found";
    });
  } catch (e) {
    stackPrint = `ERROR: ${String(e)}`;
  }

  fs.writeFileSync(OUT_TXT, stackPrint + "\n", "utf-8");

  const report = {
    url: URL,
    captured_at: nowIso(),
    signals_request_count: signalsRequests.length,
    signals_requests: signalsRequests,
    algo_entries: algoEntries,
    console_tail: consoleLines.slice(-200),
  };

  fs.writeFileSync(OUT_JSON, JSON.stringify(report, null, 2), "utf-8");

  await browser.close();

  console.log("Wrote:", OUT_JSON);
  console.log("Wrote:", OUT_TXT);
  console.log("Signals requests:", signalsRequests.length);
})();


