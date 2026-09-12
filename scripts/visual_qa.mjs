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
const requestedRoutes = new Set(
  (process.env.QA_ROUTE_NAMES || "").split(",").map((value) => value.trim()).filter(Boolean),
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
  ["journal-detail", "/journal/{journalId}/"],
  ["journal-new", "/journal/new/"],
  ["journal-edit", "/journal/{journalId}/edit/"],
  ["journal-redirect", "/journal/{journalId}/redirect/"],
  ["journal-cover", "/journal/{journalId}/cover/"],
  ["tasks", "/system/tasks/"],
  ["task-new", "/system/tasks/new/"],
  ["messages", "/system/messages/"],
  ["message-new", "/system/messages/new/"],
  ["reports", "/reports/"],
  ["report-detail", "/reports/r4_complaints/?date_from=2000-01-01"],
  ["news", "/system/news/"],
  ["news-new", "/system/news/new/"],
  ["docs", "/system/docs/"],
  ["users", "/system/users/"],
  ["user-form", "/system/users/new/"],
  ["events", "/system/events/"],
  ["exchange", "/exchange/logs/"],
  ["exchange-upload", "/exchange/upload/"],
  ["prefs", "/system/prefs/"],
  ["table-prefs", "/system/prefs/journal/"],
];
const printRoutes = [
  ["print-journal-list", "/journal/print/"],
  ["print-journal-card", "/journal/{journalId}/print/"],
  ["print-journal-cover", "/journal/{journalId}/cover/"],
];
const responsiveRouteNames = new Set([
  "events", "users", "exchange", "exchange-protocol",
  "report-detail", "journal-history", "task-history", "table-prefs",
  "user-form",
]);
if (process.env.QA_EXTRA_ROUTES) {
  const extraRoutes = JSON.parse(process.env.QA_EXTRA_ROUTES);
  if (!Array.isArray(extraRoutes) || extraRoutes.some((item) =>
    !Array.isArray(item) || item.length !== 2 || item.some((value) => typeof value !== "string")
  )) throw new Error("QA_EXTRA_ROUTES must be a JSON array of [name, path] pairs");
  routes.push(...extraRoutes);
}
if (requestedRoutes.size) {
  const knownRoutes = new Set(routes.map(([name]) => name));
  const unknownRoutes = [...requestedRoutes].filter((name) => !knownRoutes.has(name));
  if (unknownRoutes.length) throw new Error(`Unknown QA_ROUTE_NAMES: ${unknownRoutes.join(", ")}`);
  for (let index = routes.length - 1; index >= 0; index -= 1) {
    if (!requestedRoutes.has(routes[index][0])) routes.splice(index, 1);
  }
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

async function prepareRoute(name) {
  if (name !== "user-form") return;
  await evaluate(`(() => {
    const table = document.querySelector('.data--capabilities');
    const details = table?.closest('details');
    if (!details) return;
    details.open = true;
    details.scrollIntoView({ block: 'start' });
  })()`);
}

async function settleAnimations() {
  await evaluate(`new Promise((resolve) => {
    const deadline = performance.now() + 1200;
    let stableFrames = 0;
    const check = () => {
      const running = document.getAnimations().some((animation) => animation.playState === 'running');
      stableFrames = running ? 0 : stableFrames + 1;
      if (stableFrames >= 2 || performance.now() >= deadline) resolve();
      else requestAnimationFrame(check);
    };
    requestAnimationFrame(check);
  })`);
}

async function measureJournalLayout() {
  return evaluate(`(async () => {
    const wrap = document.querySelector('.table-wrap--journal');
    const table = wrap?.querySelector('table.data--journal');
    const row = table?.tBodies[0]?.rows[0];
    const groupCells = table?.tHead?.rows[0]?.cells;
    if (!wrap || !table || !row) return null;
    const mobile = innerWidth <= 720;
    const tableRect = table.getBoundingClientRect();
    const firstGroupRect = groupCells?.[0]?.getBoundingClientRect();
    const lastGroupRect = groupCells?.[groupCells.length - 1]?.getBoundingClientRect();
    const groupCoversTable = mobile || Boolean(firstGroupRect && lastGroupRect &&
      Math.abs(firstGroupRect.left - tableRect.left) <= 1 &&
      Math.abs(lastGroupRect.right - tableRect.right) <= 1);
    if (mobile) return {
      mobile,
      cardGrid: getComputedStyle(row).display === 'grid',
      headerHidden: getComputedStyle(table.tHead).display === 'none',
      groupCoversTable
    };
    wrap.scrollLeft = wrap.scrollWidth;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const wrapRect = wrap.getBoundingClientRect();
    const firstCell = row.cells[0];
    const lastCell = row.cells[row.cells.length - 1];
    const firstRect = firstCell.getBoundingClientRect();
    const lastRect = lastCell.getBoundingClientRect();
    const statusSticky = getComputedStyle(lastCell).position === 'sticky';
    const result = {
      mobile,
      internalOverflow: wrap.scrollLeft > 1,
      overflowWidth: wrap.scrollWidth - wrap.clientWidth,
      wrapClientWidth: wrap.clientWidth,
      wrapScrollWidth: wrap.scrollWidth,
      tableWidth: tableRect.width,
      overflowingDescendants: [...wrap.querySelectorAll('*')]
        .map((element) => {
          const rect = element.getBoundingClientRect();
          return {
            tag: element.tagName.toLowerCase(),
            className: typeof element.className === 'string' ? element.className : '',
            rightOverflow: Math.max(0, rect.right - wrapRect.right)
          };
        })
        .filter((item) => item.rightOverflow > 1)
        .slice(0, 8),
      groupCoversTable,
      firstPinned: getComputedStyle(firstCell).position === 'sticky' &&
        Math.abs(firstRect.left - wrapRect.left) <= 2,
      statusSticky,
      statusPinned: !statusSticky || Math.abs(lastRect.right - wrapRect.right) <= 2
    };
    wrap.scrollLeft = 0;
    return result;
  })()`);
}

async function measureTaskLayout() {
  return evaluate(`(() => {
    const wrap = document.querySelector('.table-wrap--tasks');
    const table = wrap?.querySelector('table.data--tasks');
    const row = table?.querySelector('tbody tr.task-row');
    const actions = row?.querySelector('.table-actions');
    if (!wrap || !table || !row || !actions) return null;
    const compact = innerWidth <= 1100;
    const wrapRect = wrap.getBoundingClientRect();
    const actionsRect = actions.getBoundingClientRect();
    return {
      compact,
      headerHidden: getComputedStyle(table.tHead).display === 'none',
      cardGrid: getComputedStyle(row).display === 'grid',
      actionsVisible: actionsRect.left >= wrapRect.left - 1 && actionsRect.right <= wrapRect.right + 1
    };
  })()`);
}

async function measureResponsiveTable() {
  return evaluate(`(() => {
    const table = document.querySelector('table.data--responsive');
    const wrap = table?.closest('.table-wrap--responsive');
    const row = table?.querySelector('tbody tr.responsive-row');
    if (!wrap || !table) return null;
    wrap.scrollLeft = wrap.scrollWidth;
    const actions = row?.querySelector('.table-actions, .responsive-cell--actions > a');
    const wrapRect = wrap.getBoundingClientRect();
    const actionsRect = actions?.getBoundingClientRect();
    return {
      compact: innerWidth <= 900,
      headerHidden: getComputedStyle(table.tHead).display === 'none',
      empty: !row,
      cardGrid: !row || getComputedStyle(row).display === 'grid',
      horizontallyScrollable: wrap.scrollLeft > 1,
      actionsVisible: !actionsRect ||
        (actionsRect.left >= wrapRect.left - 1 && actionsRect.right <= wrapRect.right + 1)
    };
  })()`);
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

  const results = [];
  async function captureLogin(width, height, theme, font, contrast) {
    await command("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    const errorStart = browserErrors.length;
    await navigate(`${baseUrl}/accounts/login/`);
    await evaluate(`document.documentElement.dataset.theme=${JSON.stringify(theme)}; document.documentElement.dataset.font=${JSON.stringify(font)}; document.documentElement.dataset.contrast=${JSON.stringify(contrast)}`);
    await settleAnimations();
    const metrics = await evaluate(`(() => ({
      path: location.pathname,
      title: document.title,
      httpStatus: performance.getEntriesByType('navigation')[0]?.responseStatus || null,
      forbidden: false,
      documentOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
      navOverflow: false,
      appliedMode: {
        theme: document.documentElement.dataset.theme || null,
        font: document.documentElement.dataset.font || null,
        contrast: document.documentElement.dataset.contrast || null
      },
      activeAnimations: document.getAnimations().filter((animation) => animation.playState === 'running').length,
      tablePalette: [],
      width: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth
    }))()`);
    metrics.journalLayout = null;
    metrics.taskLayout = null;
    metrics.responsiveTable = null;
    metrics.browserErrors = browserErrors.slice(errorStart);
    const shot = await command("Page.captureScreenshot", { format: "png", fromSurface: true });
    const suffix = theme === "light" && font === "base" && contrast === "default"
      ? "light"
      : `${theme}-${font}-${contrast}`;
    const filename = `login-${width}x${height}-${suffix}.png`;
    await writeFile(join(outputDir, filename), Buffer.from(shot.data, "base64"));
    results.push({ name: "login", viewport: `${width}x${height}`, theme, font, contrast, ...metrics, screenshot: filename });
  }

  for (const [width, height] of viewports) {
    await captureLogin(width, height, "light", "base", "default");
  }
  for (const [theme, font, contrast] of [["dark", "base", "default"], ["light", "a-plus-plus", "default"], ["light", "a", "black"]]) {
    for (const [width, height] of [[694, 869], [1024, 768], [1920, 1080]]) {
      await captureLogin(width, height, theme, font, contrast);
    }
  }

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

  if ([...routes, ...printRoutes].some(([, path]) => path.includes("{journalId}"))) {
    await navigate(`${baseUrl}/journal/`);
    const journalPath = await evaluate(
      "document.querySelector('a.table-row-link')?.getAttribute('href') || null",
    );
    const journalMatch = journalPath?.match(/^\/journal\/(\d+)\/$/);
    if (!journalMatch) {
      throw new Error("Journal detail routes require at least one record visible to the QA account.");
    }
    for (const route of routes) route[1] = route[1].replaceAll("{journalId}", journalMatch[1]);
    for (const route of printRoutes) route[1] = route[1].replaceAll("{journalId}", journalMatch[1]);
  }

  for (const [width, height] of viewports) {
    await command("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile: false });
    for (const [name, path] of routes) {
      const errorStart = browserErrors.length;
      await navigate(`${baseUrl}${path}`);
      await evaluate(`document.documentElement.dataset.theme='light'; document.documentElement.dataset.font='base'; document.documentElement.dataset.contrast='default'`);
      await prepareRoute(name);
      await settleAnimations();
      const metrics = await evaluate(`(() => ({
        path: location.pathname,
        title: document.title,
        httpStatus: performance.getEntriesByType('navigation')[0]?.responseStatus || null,
        forbidden: document.querySelector('.error-page__code')?.textContent.trim() === '403',
        documentOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        navOverflow: Boolean(document.querySelector('.nav__scroll')) && document.querySelector('.nav__scroll').scrollWidth > document.querySelector('.nav__scroll').clientWidth + 1,
        appliedMode: {
          theme: document.documentElement.dataset.theme || null,
          font: document.documentElement.dataset.font || null,
          contrast: document.documentElement.dataset.contrast || null
        },
        activeAnimations: document.getAnimations().filter((animation) => animation.playState === 'running').length,
        tablePalette: [...document.querySelectorAll('table.data tbody tr')].slice(0, 4).map((row) => ({
          row: getComputedStyle(row).backgroundColor,
          firstCell: row.cells[0] ? getComputedStyle(row.cells[0]).backgroundColor : null,
          middleCell: row.cells[1] ? getComputedStyle(row.cells[1]).backgroundColor : null,
          lastCell: row.cells.length ? getComputedStyle(row.cells[row.cells.length - 1]).backgroundColor : null
        })),
        width: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth
      }))()`);
      metrics.journalLayout = name === "journal" ? await measureJournalLayout() : null;
      metrics.taskLayout = name === "tasks" ? await measureTaskLayout() : null;
      metrics.responsiveTable = responsiveRouteNames.has(name) ? await measureResponsiveTable() : null;
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
        await prepareRoute(name);
        await settleAnimations();
      const metrics = await evaluate(`(() => ({
          path: location.pathname,
          title: document.title,
          httpStatus: performance.getEntriesByType('navigation')[0]?.responseStatus || null,
          forbidden: document.querySelector('.error-page__code')?.textContent.trim() === '403',
          documentOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
          navOverflow: Boolean(document.querySelector('.nav__scroll')) && document.querySelector('.nav__scroll').scrollWidth > document.querySelector('.nav__scroll').clientWidth + 1,
          appliedMode: {
            theme: document.documentElement.dataset.theme || null,
            font: document.documentElement.dataset.font || null,
            contrast: document.documentElement.dataset.contrast || null
          },
          activeAnimations: document.getAnimations().filter((animation) => animation.playState === 'running').length,
          tablePalette: [...document.querySelectorAll('table.data tbody tr')].slice(0, 4).map((row) => ({
            row: getComputedStyle(row).backgroundColor,
            firstCell: row.cells[0] ? getComputedStyle(row.cells[0]).backgroundColor : null,
            middleCell: row.cells[1] ? getComputedStyle(row.cells[1]).backgroundColor : null,
            lastCell: row.cells.length ? getComputedStyle(row.cells[row.cells.length - 1]).backgroundColor : null
          })),
          width: document.documentElement.clientWidth,
          scrollWidth: document.documentElement.scrollWidth
        }))()`);
        metrics.journalLayout = name === "journal" ? await measureJournalLayout() : null;
        metrics.taskLayout = name === "tasks" ? await measureTaskLayout() : null;
        metrics.responsiveTable = responsiveRouteNames.has(name) ? await measureResponsiveTable() : null;
        metrics.browserErrors = browserErrors.slice(errorStart);
        const shot = await command("Page.captureScreenshot", { format: "png", fromSurface: true });
        const filename = `${name}-${width}x${height}-${theme}-${font}-${contrast}.png`;
        await writeFile(join(outputDir, filename), Buffer.from(shot.data, "base64"));
        results.push({ name, viewport: `${width}x${height}`, theme, font, contrast, ...metrics, screenshot: filename });
      }
    }
  }

  await command("Emulation.setEmulatedMedia", { media: "print" });
  await command("Emulation.setDeviceMetricsOverride", { width: 1240, height: 1754, deviceScaleFactor: 1, mobile: false });
  for (const [name, path] of printRoutes) {
    const errorStart = browserErrors.length;
    await navigate(`${baseUrl}${path}`);
    await settleAnimations();
    const metrics = await evaluate(`(() => {
      const sheet = document.querySelector('.paper, .print-sheet');
      const sheetStyle = sheet ? getComputedStyle(sheet) : null;
      return {
        path: location.pathname,
        title: document.title,
        httpStatus: performance.getEntriesByType('navigation')[0]?.responseStatus || null,
        forbidden: false,
        documentOverflow: document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
        navOverflow: false,
        appliedMode: { theme: 'light', font: 'base', contrast: 'default' },
        activeAnimations: document.getAnimations().filter((animation) => animation.playState === 'running').length,
        tablePalette: [],
        width: document.documentElement.clientWidth,
        scrollWidth: document.documentElement.scrollWidth,
        printLayout: {
          screenControlsHidden: [...document.querySelectorAll('.no-print, .header, .nav, .footer')]
            .every((element) => getComputedStyle(element).display === 'none'),
          sheetReset: Boolean(sheetStyle) && sheetStyle.borderTopStyle === 'none' &&
            sheetStyle.boxShadow === 'none' && sheetStyle.paddingTop === '0px',
          tableHeadersStatic: [...document.querySelectorAll('table.data th')]
            .every((element) => getComputedStyle(element).position === 'static'),
          letterRowsNeutral: [...document.querySelectorAll('.letter-table th, .letter-table td')]
            .every((element) => ['rgb(255, 255, 255)', 'rgb(244, 246, 248)']
              .includes(getComputedStyle(element).backgroundColor))
        }
      };
    })()`);
    metrics.journalLayout = null;
    metrics.taskLayout = null;
    metrics.responsiveTable = null;
    metrics.browserErrors = browserErrors.slice(errorStart);
    const pdf = await command("Page.printToPDF", { printBackground: true, preferCSSPageSize: true });
    const filename = `${name}.pdf`;
    await writeFile(join(outputDir, filename), Buffer.from(pdf.data, "base64"));
    results.push({ name, viewport: "print", theme: "light", font: "base", contrast: "default", ...metrics, pdf: filename });
  }
  await command("Emulation.setEmulatedMedia", { media: "screen" });

  const checkedResults = results.map((item) => ({
    ...item,
    expectedForbidden: expectedForbidden.has(item.name),
    modeMismatch: item.appliedMode.theme !== item.theme ||
      item.appliedMode.font !== item.font ||
      item.appliedMode.contrast !== (item.contrast || "default"),
    journalLayoutMismatch: item.name === "journal" && (!item.journalLayout ||
      !item.journalLayout.groupCoversTable ||
      (item.journalLayout.mobile
        ? (!item.journalLayout.cardGrid || !item.journalLayout.headerHidden)
        : (!item.journalLayout.firstPinned || !item.journalLayout.statusPinned ||
          (item.width >= 1366 && item.journalLayout.internalOverflow)))),
    taskLayoutMismatch: item.name === "tasks" && item.width <= 1100 &&
      (!item.taskLayout || !item.taskLayout.compact || !item.taskLayout.headerHidden ||
        !item.taskLayout.cardGrid || !item.taskLayout.actionsVisible),
    responsiveTableMismatch: responsiveRouteNames.has(item.name) && item.width <= 900 &&
      (!item.responsiveTable || !item.responsiveTable.compact ||
        !item.responsiveTable.headerHidden || !item.responsiveTable.cardGrid ||
        item.responsiveTable.horizontallyScrollable || !item.responsiveTable.actionsVisible),
    printLayoutMismatch: item.name.startsWith("print-") && (!item.printLayout ||
      !item.printLayout.screenControlsHidden || !item.printLayout.sheetReset ||
      !item.printLayout.tableHeadersStatic || !item.printLayout.letterRowsNeutral),
  }));
  const report = {
    generatedAt: new Date().toISOString(),
    baseUrl,
    cases: results.length,
    expectedForbidden: [...expectedForbidden],
    failures: checkedResults.filter((item) =>
      item.documentOverflow || (item.width >= 1024 && item.navOverflow) ||
      (item.name !== "login" && item.path.includes("login")) ||
      (item.httpStatus >= 400 && !(item.expectedForbidden && item.httpStatus === 403)) ||
      item.forbidden !== item.expectedForbidden || item.browserErrors.length || item.modeMismatch ||
      item.journalLayoutMismatch || item.taskLayoutMismatch || item.responsiveTableMismatch ||
      item.printLayoutMismatch || item.activeAnimations
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
