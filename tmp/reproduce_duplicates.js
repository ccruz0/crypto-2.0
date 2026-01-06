const { chromium } = require("../frontend/node_modules/playwright");
const fs = require("fs");

(async () => {
  console.log("🔍 Reproducing duplicate signals requests...");
  
  const browser = await chromium.launch({ headless: false });
  const page = await browser.newPage();
  
  const consoleMessages = [];
  const signalsRequests = [];
  
  // Capture console messages
  page.on("console", (msg) => {
    const text = msg.text();
    if (text.includes("[signals-http]") || text.includes("DUPLICATE")) {
      consoleMessages.push({
        type: msg.type(),
        text: text,
        timestamp: Date.now()
      });
    }
  });
  
  // Capture network requests
  page.on("request", (req) => {
    const url = req.url();
    if (url.includes("/api/signals")) {
      signalsRequests.push({
        url,
        timestamp: Date.now(),
        method: req.method()
      });
    }
  });
  
  try {
    console.log("📱 Navigating to http://localhost:3000...");
    await page.goto("http://localhost:3000", { waitUntil: "domcontentloaded", timeout: 60000 });
    
    console.log("⏳ Waiting 10 seconds for requests...");
    await page.waitForTimeout(10000);
    
    // Get counter data
    const counterData = await page.evaluate(() => {
      return {
        sigCount: window.__SIG_COUNT__ || {},
        signalsHttp: window.__SIGNALS_HTTP__ || []
      };
    });
    
    console.log("\n📊 SIGNALS COUNTER DATA:");
    console.log(JSON.stringify(counterData.sigCount, null, 2));
    
    console.log("\n📊 NETWORK REQUESTS:");
    const bySymbol = {};
    signalsRequests.forEach(req => {
      const match = req.url.match(/symbol=([^&]+)/);
      if (match) {
        const symbol = match[1];
        if (!bySymbol[symbol]) bySymbol[symbol] = [];
        bySymbol[symbol].push(req);
      }
    });
    Object.entries(bySymbol).forEach(([symbol, reqs]) => {
      console.log(`${symbol}: ${reqs.length} request(s)`);
      if (reqs.length > 1) {
        console.log(`  ⚠️ DUPLICATE DETECTED for ${symbol}!`);
        reqs.forEach((req, idx) => {
          console.log(`    [${idx + 1}] ${new Date(req.timestamp).toISOString()}`);
        });
      }
    });
    
    // Take screenshots
    await page.screenshot({ path: "tmp/repro_console.png", fullPage: true });
    console.log("\n📸 Screenshot saved: tmp/repro_console.png");
    
    // Save console messages
    fs.writeFileSync("tmp/repro_console_messages.json", JSON.stringify(consoleMessages, null, 2));
    console.log("📝 Console messages saved: tmp/repro_console_messages.json");
    
    // Save network requests
    fs.writeFileSync("tmp/repro_network_requests.json", JSON.stringify(signalsRequests, null, 2));
    console.log("📝 Network requests saved: tmp/repro_network_requests.json");
    
  } catch (error) {
    console.error("❌ Error:", error);
  } finally {
    await browser.close();
  }
})();

