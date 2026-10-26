import { chromium } from "playwright";
import path from "node:path";

const TOKEN = process.env.STOCKOS_DEMO_TOKEN || "";

const SHOTS = "./shots";
const CLIPS = "./clips";

async function injectOverlay(page) {
  await page.addInitScript((token) => {
    localStorage.setItem("sm_token", token);
    const style = document.createElement("style");
    style.textContent = `
      #demo-cursor { position: fixed; width: 18px; height: 18px; border-radius: 50%; background: rgba(59,130,246,0.9); border: 2px solid white; box-shadow: 0 0 0 2px rgba(59,130,246,0.4); pointer-events: none; z-index: 2147483647; transform: translate(-50%, -50%); transition: left 0.08s ease, top 0.08s ease; }
      #demo-caption { position: fixed; left: 0; right: 0; bottom: 0; height: 56px; background: rgba(15,23,42,0.92); color: white; display: flex; align-items: center; justify-content: center; font: 600 20px/1.2 system-ui, -apple-system, Segoe UI, Roboto, sans-serif; z-index: 2147483646; padding: 0 24px; text-align: center; }
    `;
    document.head.appendChild(style);
    const cursor = document.createElement("div");
    cursor.id = "demo-cursor";
    cursor.style.left = "640px";
    cursor.style.top = "360px";
    document.body.appendChild(cursor);
    const caption = document.createElement("div");
    caption.id = "demo-caption";
    caption.textContent = "";
    document.body.appendChild(caption);
    window.addEventListener("mousemove", (e) => {
      cursor.style.left = e.clientX + "px";
      cursor.style.top = e.clientY + "px";
    });
    window.__setCaption = (t) => { caption.textContent = t; };
  }, TOKEN);
}

async function caption(page, text) {
  await page.evaluate((t) => window.__setCaption && window.__setCaption(t), text);
  await page.waitForTimeout(2000);
}

async function slowType(locator, text) {
  await locator.click();
  await locator.type(text, { delay: 80 });
}

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 720 },
    recordVideo: { dir: CLIPS, size: { width: 1280, height: 720 } },
  });
  const page = await context.newPage();
  await injectOverlay(page);

  // 1. Hook
  await page.goto("http://localhost:3000/");
  await page.waitForLoadState("networkidle");
  await caption(page, "What is StockOS AI?");
  await page.screenshot({ path: path.join(SHOTS, "05-hook.png") });
  await page.waitForTimeout(2000);

  // 2. Feature 1 - Live Market Dashboard
  await page.getByRole("button", { name: "Market" }).click();
  await page.waitForTimeout(500);
  await page.getByRole("link", { name: "Dashboard" }).click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2000);
  await page.goto("http://localhost:3000/stock/NSE:RELIANCE");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(4000);
  await caption(page, "Live market dashboard: quotes, charts, and watchlists");
  await page.screenshot({ path: path.join(SHOTS, "01-dashboard.png") });
  await page.waitForTimeout(2000);

  // 3. Feature 2 - Technical Indicators
  await page.waitForTimeout(2000);
  await page.waitForSelector("text=SMA20", { timeout: 20000 });
  await page.getByText("SMA20", { exact: true }).click();
  await page.waitForTimeout(800);
  await page.getByText("SMA20", { exact: true }).click();
  await page.waitForTimeout(800);
  await page.getByText("Bollinger", { exact: true }).click();
  await page.waitForTimeout(800);
  await page.getByText("Bollinger", { exact: true }).click();
  await page.waitForTimeout(2000);
  await caption(page, "Technical indicators with buy/sell signal markers");
  await page.screenshot({ path: path.join(SHOTS, "02-indicators.png") });
  await page.waitForTimeout(2000);

  // 4. Feature 3 - AI Prediction
  await page.getByRole("button", { name: "Analytics" }).click();
  await page.waitForTimeout(500);
  await page.getByRole("link", { name: "Prediction" }).click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2000);
  const searchInput = page.getByPlaceholder("Search stocks...");
  await slowType(searchInput, "RELIANCE");
  await page.waitForTimeout(1500);
  await page.getByRole("button", { name: /RELIANCE/i }).first().click();
  await page.waitForTimeout(1000);
  await page.getByRole("button", { name: "Predict" }).first().click();
  await page.waitForTimeout(8000);
  await caption(page, "AI prediction: price target, scenarios, and reasoning");
  await page.screenshot({ path: path.join(SHOTS, "03-prediction.png") });
  await page.waitForTimeout(2000);

  // 5. Feature 4 - Paper Trading Terminal
  await page.getByRole("button", { name: "Trading" }).click();
  await page.waitForTimeout(500);
  await page.getByRole("link", { name: "Terminal" }).click();
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(4000);
  const cmdInput = page.getByPlaceholder(/Type a command/);
  await slowType(cmdInput, "buy NSE:RELIANCE 1");
  await page.waitForTimeout(500);
  await cmdInput.press("Enter");
  await page.waitForTimeout(4000);
  await caption(page, "Paper trading terminal: commands, positions, P&L, risk");
  await page.screenshot({ path: path.join(SHOTS, "04-terminal.png") });
  await page.waitForTimeout(2000);

  // 6. Outro
  await caption(page, "StockOS AI - github.com/PRATIK082/StockOS_AI");
  await page.screenshot({ path: path.join(SHOTS, "06-outro.png") });
  await page.waitForTimeout(2000);

  await context.close();
  await browser.close();
  console.log("Demo recording complete");
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
