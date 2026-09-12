#!/usr/bin/env node

import { spawn } from "node:child_process";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

const baseUrl = (process.env.QA_BASE_URL || "http://127.0.0.1:8765").replace(/\/$/, "");
const username = process.env.QA_USERNAME;
const password = process.env.QA_PASSWORD;
const chromePath = process.env.CHROME_PATH || "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const outputDir = process.env.QA_OUTPUT_DIR || ".artifacts/visual-qa";
const expectedForbidden = new Set(
  (process.env.QA_EXPECT_FORBIDDEN || "").split(",").map((value) => value.trim()).filter(Boolean),
);

if (!username || !password) {
  console.error("Set QA_USERNAME and QA_PASSWORD for a local non-production account.");
  process.exit(2);
}

const viewports = [
  [694, 869],
  [1024, 768],
  [1280, 800],
  [1366, 768],
  [1440, 900],
  [1920, 1080],
];
const routes = [
  ["journal", "/journal/"],
  ["journal-detail", "/journal/1/"],
  ["journal-new", "/journal/new/"],
  ["tasks", "/system/tasks/"],
  ["messages", "/system/messages/"],
  ["reports", "/reports/"],
  ["news", "/system/news/"],
  ["docs", "/system/docs/"],
  ["users", "/system/users/"],
  ["events", "/system/events/"],
  ["exchange", "/exchange/logs/"],
];
if (process.env.QA_EXTRA_ROUTES) {
  const extraRoutes = JSON.parse(process.env.QA_EXTRA_ROUTES);
  if (!Array.isArray(extraRoutes) || extraRoutes.some((item) =>
    !Array.isArray(item) || item.length !== 2 || item.some((value) => typeof value !== "string")
  )) throw new Error("QA_EXTRA_ROUTES must be a JSON array of [name, path] pairs");
  routes.push(...extraRoutes);
}

const profileDir = await mkdtemp(join(tmpdir(), "ofoms-visual-qa-"));
await mkdir(outputDir, { recursive: true });
const chrome = spawn(chromePath, [
  "--headless=new",
  "--disable-gpu",
  "--no-first-run",
  "--no-default-browser-check",
  "--remote-debugging-port=0",
  `--user-data-dir=${profileDir}`,
  "about:blank",
], { stdio: "ignore" });

const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function devtoolsPort() {
  const file = join(profileDir, "DevToolsActivePort");
  for (let i = 0; i < 100; i += 1) {
    try { return (await readFile(file, "utf8")).split("\n")[0]; } catch { await pause(50); }
  }
  throw new Error("Chrome DevTools port was not created");
}

let socket;
let messageId = 0;
const pending = new Map();
const eventWaiters = new Map();
const browserErrors = [];
function command(method, params = {}) {
  const id = ++messageId;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}
function waitEvent(method, timeout = 15000) {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`Timeout waiting for ${method}`)), timeout);
    eventWaiters.set(method, (params) => { clearTimeout(timer); eventWaiters.delete(method); resolve(params); });
  });
}
async function navigate(url) {
  const loaded = waitEvent("Page.loadEventFired");
  await command("Page.navigate", { url });
  await loaded;
  await pause(180);
}
async function evaluate(expression) {
  const result = await command("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) {
    const description = result.exceptionDetails.exception?.description || result.exceptionDetails.text;
    throw new Error(description);
  }
  return result.result.value;
}

try {
  const port = await devtoolsPort();
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = pages.find((target) => target.type === "page" && !target.url.startsWith("chrome-extension://"));
  if (!page) throw new Error("Chrome page target was not found");
  socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  socket.onmessage = ({ data }) => {
    const message = JSON.parse(data);
    if (message.id && pending.has(message.id)) {
      const waiter = pending.get(message.id); pending.delete(message.id);
      if (message.error) waiter.reject(new Error(message.error.message)); else waiter.resolve(message.result);
    } else if (eventWaiters.has(message.method)) {
      eventWaiters.get(message.method)(message.params);
    } else if (
      message.method === "Log.entryAdded" &&
      message.params.entry.level === "error" &&
      ["javascript", "security"].includes(message.params.entry.source)
    ) {
      browserErrors.push(message.params.entry.text);
    } else if (message.method === "Runtime.exceptionThrown") {
      browserErrors.push(
        message.params.exceptionDetails.exception?.description ||
        message.params.exceptionDetails.text ||
        "Uncaught JavaScript exception",
      );
    }
  };
  await command("Page.enable");
  await command("Runtime.enable");
  await command("Log.enable");

  await navigate(`${baseUrl}/accounts/login/`);
  const loginFormReady = await evaluate(`Boolean(
    document.querySelector('[name="username"]') &&
    document.querySelector('[name="password"]') &&
    document.querySelector('form')
  )`);
  if (!loginFormReady) throw new Error(`Login form was not found at ${await evaluate("location.href")}`);
  await evaluate(`(() => {
    document.querySelector('[name="username"]').value = ${JSON.stringify(username)};
    document.querySelector('[name="password"]').value = ${JSON.stringify(password)};
  })()`);
  const loginLoaded = waitEvent("Page.loadEventFired");
  await evaluate("document.querySelector('form').requestSubmit()");
  await loginLoaded;
  if ((await evaluate("location.pathname")).includes("login")) throw new Error("QA login failed");
  if (browserErrors.length) {
    throw new Error(`Browser error during login: ${browserErrors.join(" | ")}`);
  }

  const results = [];
  for (const [width, height] of viewports) {
    await command("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    for (const [name, path] of routes) {
      const errorStart = browserErrors.length;
      await navigate(`${baseUrl}${path}`);
      await evaluate(`document.documentElement.dataset.theme='light'; document.documentElement.dataset.font='base'; document.documentElement.dataset.contrast='default'`);
      await pause(180);
      const metrics = await evaluate(`(() => ({
        path: location.pathname,
        title: document.title,
        forbidden: document.querySelector('.error-page__code')?.textContent.trim() === '403',
        documentOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        navOverflow: Boolean(document.querySelector('.nav__scroll')) && document.querySelector('.nav__scroll').scrollWidth > document.querySelector('.nav__scroll').clientWidth + 1,
        tablePalette: [...document.querySelectorAll('table.data tbody tr')].slice(0, 4).map((row) => ({
          row: getComputedStyle(row).backgroundColor,
          firstCell: row.cells[0] ? getComputedStyle(row.cells[0]).backgroundColor : null,
          middleCell: row.cells[1] ? getComputedStyle(row.cells[1]).backgroundColor : null,
          lastCell: row.cells.length ? getComputedStyle(row.cells[row.cells.length - 1]).backgroundColor : null
        })),
        width: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth
      }))()`);
      metrics.browserErrors = browserErrors.slice(errorStart);
      const shot = await command("Page.captureScreenshot", { format: "png", fromSurface: true });
      const filename = `${name}-${width}x${height}-light.png`;
      await writeFile(join(outputDir, filename), Buffer.from(shot.data, "base64"));
      results.push({ name, viewport: `${width}x${height}`, theme: "light", font: "base", ...metrics, screenshot: filename });
    }
  }

  for (const [theme, font, contrast] of [["dark", "base", "default"], ["light", "a-plus-plus", "default"], ["light", "a", "black"]]) {
    for (const [width, height] of [[694, 869], [1024, 768], [1920, 1080]]) {
      await command("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
      for (const [name, path] of routes) {
        const errorStart = browserErrors.length;
        await navigate(`${baseUrl}${path}`);
        await evaluate(`document.documentElement.dataset.theme=${JSON.stringify(theme)}; document.documentElement.dataset.font=${JSON.stringify(font)}; document.documentElement.dataset.contrast=${JSON.stringify(contrast)}`);
        await pause(180);
      const metrics = await evaluate(`(() => ({
          path: location.pathname,
          title: document.title,
          forbidden: document.querySelector('.error-page__code')?.textContent.trim() === '403',
          documentOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
          navOverflow: Boolean(document.querySelector('.nav__scroll')) && document.querySelector('.nav__scroll').scrollWidth > document.querySelector('.nav__scroll').clientWidth + 1,
          tablePalette: [...document.querySelectorAll('table.data tbody tr')].slice(0, 4).map((row) => ({
            row: getComputedStyle(row).backgroundColor,
            firstCell: row.cells[0] ? getComputedStyle(row.cells[0]).backgroundColor : null,
            middleCell: row.cells[1] ? getComputedStyle(row.cells[1]).backgroundColor : null,
            lastCell: row.cells.length ? getComputedStyle(row.cells[row.cells.length - 1]).backgroundColor : null
          })),
          width: document.documentElement.clientWidth,
          scrollWidth: document.documentElement.scrollWidth
        }))()`);
        metrics.browserErrors = browserErrors.slice(errorStart);
        const shot = await command("Page.captureScreenshot", { format: "png", fromSurface: true });
        const filename = `${name}-${width}x${height}-${theme}-${font}-${contrast}.png`;
        await writeFile(join(outputDir, filename), Buffer.from(shot.data, "base64"));
        results.push({ name, viewport: `${width}x${height}`, theme, font, contrast, ...metrics, screenshot: filename });
      }
    }
  }

  const checkedResults = results.map((item) => ({
    ...item,
    expectedForbidden: expectedForbidden.has(item.name),
  }));
  const report = {
    generatedAt: new Date().toISOString(),
    baseUrl,
    cases: results.length,
    expectedForbidden: [...expectedForbidden],
    failures: checkedResults.filter((item) =>
      item.documentOverflow || (item.width >= 1024 && item.navOverflow) || item.path.includes("login") || item.forbidden !== item.expectedForbidden || item.browserErrors.length
    ),
    results: checkedResults,
  };
  await writeFile(join(outputDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`);
  console.log(`Visual QA: ${report.cases} cases, ${report.failures.length} failures. Report: ${join(outputDir, "report.json")}`);
  if (report.failures.length) process.exitCode = 1;
} finally {
  if (socket) socket.close();
  if (chrome.exitCode === null && !chrome.killed) chrome.kill("SIGTERM");
  if (chrome.exitCode === null) {
    await Promise.race([
      new Promise((resolve) => chrome.once("exit", resolve)),
      pause(2_000),
    ]);
  }
  try {
    await rm(profileDir, {
      recursive: true,
      force: true,
      maxRetries: 5,
      retryDelay: 150,
    });
  } catch (error) {
    console.warn(`Could not remove temporary Chrome profile ${profileDir}: ${error.message}`);
  }
}
