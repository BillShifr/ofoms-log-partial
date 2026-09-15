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
const expectedStatuses = new Map(Object.entries(
  process.env.QA_EXPECT_STATUSES ? JSON.parse(process.env.QA_EXPECT_STATUSES) : {},
).map(([name, status]) => [name, Number(status)]));
if ([...expectedStatuses.values()].some((status) => !Number.isInteger(status) || status < 100 || status > 599)) {
  throw new Error("QA_EXPECT_STATUSES must map route names to valid HTTP status codes");
}

if (!username || !password) {
  console.error("Set QA_USERNAME and QA_PASSWORD for a local non-production account.");
  process.exit(2);
}

const viewports = [
  [390, 844],
  [768, 1024],
  [1024, 768],
  [1280, 800],
  [1366, 768],
  [1440, 900],
  [1920, 1080],
];
const sampledModeViewports = [
  [390, 844],
  [768, 1024],
  [1024, 768],
  [1920, 1080],
];
const accessibilityModes = [
  ["dark", "base", "default"],
  ["light", "a", "default"],
  ["light", "a-plus-plus", "default"],
  ["light", "base", "black"],
  ["light", "base", "white"],
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
  const knownRoutes = new Set([...routes, ...printRoutes].map(([name]) => name));
  const unknownRoutes = [...requestedRoutes].filter((name) => !knownRoutes.has(name));
  if (unknownRoutes.length) throw new Error(`Unknown QA_ROUTE_NAMES: ${unknownRoutes.join(", ")}`);
  for (let index = routes.length - 1; index >= 0; index -= 1) {
    if (!requestedRoutes.has(routes[index][0])) routes.splice(index, 1);
  }
  for (let index = printRoutes.length - 1; index >= 0; index -= 1) {
    if (!requestedRoutes.has(printRoutes[index][0])) printRoutes.splice(index, 1);
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
    const table = document.querySelector('table.data[data-table-key="system-capabilities"]');
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
    const table = document.querySelector('table.data[data-table-key="journal"]');
    const wrap = table?.closest('.table-wrap');
    const row = table?.tBodies[0]?.rows[0];
    if (!wrap || !table || !row) return null;
    const mobile = false;
    const tableRect = table.getBoundingClientRect();
    const groupRowsRemoved = table.querySelectorAll('.group-row, .group-row__label').length === 0;
    wrap.scrollLeft = wrap.scrollWidth;
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const wrapRect = wrap.getBoundingClientRect();
    const firstCell = row.cells[0];
    const lastCell = row.cells[row.cells.length - 1];
    const firstRect = firstCell.getBoundingClientRect();
    const lastRect = lastCell.getBoundingClientRect();
    const statusSticky = getComputedStyle(lastCell).position === 'sticky';
    const sortableHeaders = [...table.tHead.querySelectorAll('th[aria-sort]')];
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
      groupRowsRemoved,
      firstPinned: getComputedStyle(firstCell).position === 'sticky' &&
        Math.abs(firstRect.left - wrapRect.left) <= 2,
      statusSticky,
      statusPinned: !statusSticky || Math.abs(lastRect.right - wrapRect.right) <= 2,
      sortableHeaders: sortableHeaders.length,
      sortIndicatorsVisible: sortableHeaders.length > 0 &&
        sortableHeaders.every((header) => getComputedStyle(header, '::after').content !== 'none')
    };
    wrap.scrollLeft = 0;
    return result;
  })()`);
}

async function measureTaskLayout() {
  return evaluate(`(() => {
    const table = document.querySelector('table.data[data-table-key="system-tasks"]');
    const wrap = table?.closest('.table-wrap');
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
      actionCellSticky: getComputedStyle(actions.closest('td')).position === 'sticky',
      actionsVisible: actionsRect.left >= wrapRect.left - 1 && actionsRect.right <= wrapRect.right + 1
    };
  })()`);
}

async function measureCollapsibleLayout() {
  return evaluate(`(() => {
    const panel = document.querySelector('details.collapsible');
    const toggle = panel?.querySelector('.collapsible__toggle');
    if (!panel || !toggle) return null;
    if (panel.open) return null;
    const panelStyle = getComputedStyle(panel);
    const toggleStyle = getComputedStyle(toggle);
    const markerContent = getComputedStyle(toggle, '::after').content;
    const toggleRect = toggle.getBoundingClientRect();
    return {
      closed: !panel.open,
      hasBorder: panelStyle.borderTopStyle !== 'none' && panelStyle.borderTopWidth !== '0px',
      clipsRoundedHeader: panelStyle.overflow !== 'visible',
      hasLeftStateBar: toggleStyle.boxShadow !== 'none',
      hasStateText: markerContent !== 'none' && markerContent !== '""',
      minTapHeight: toggleRect.height >= 40
    };
  })()`);
}

async function measureFormContainment() {
  return evaluate(`(() => {
    const containers = [...document.querySelectorAll('.card, details.collapsible, fieldset.field-group, .form-grid, .filters')];
    const inspectable = [...document.querySelectorAll('.field, .field-group, .form-grid, input, select, textarea, .collapsible__toggle, .form-section-heading')]
      .filter((element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return element.type !== 'hidden' && !element.closest('.table-wrap') &&
          style.display !== 'none' && style.visibility !== 'hidden' &&
          rect.width > 0 && rect.height > 0;
      });
    const overflowing = [];
    const containerFor = (element) => {
      if (element.matches('input, select, textarea')) return element.closest('.field, fieldset.field-group, details.collapsible, .card');
      if (element.matches('.field')) return element.closest('fieldset.field-group, .form-grid, .filters, details.collapsible, .card');
      if (element.matches('.field-group')) return element.closest('.filters, details.collapsible, .card');
      if (element.matches('.form-grid')) return element.closest('details.collapsible, .card');
      return element.closest('details.collapsible, .card');
    };
    for (const element of inspectable) {
      const container = containerFor(element);
      if (!container) continue;
      const rect = element.getBoundingClientRect();
      const bounds = container.getBoundingClientRect();
      const overflow = Math.max(0, rect.right - bounds.right, bounds.left - rect.left);
      if (overflow > 1) {
        overflowing.push({
          tag: element.tagName.toLowerCase(),
          className: typeof element.className === 'string' ? element.className : '',
          container: container.tagName.toLowerCase() + (container.className ? '.' + String(container.className).replace(/\\s+/g, '.') : ''),
          overflow: Math.round(overflow)
        });
      }
    }
    const adjacentCollapsibles = [...document.querySelectorAll('details.collapsible + details.collapsible')];
    const gaps = adjacentCollapsibles.map((panel) => {
      const previous = panel.previousElementSibling;
      if (!previous) return 0;
      return Math.round(panel.getBoundingClientRect().top - previous.getBoundingClientRect().bottom);
    });
    return {
      containerCount: containers.length,
      overflowCount: overflowing.length,
      overflowing: overflowing.slice(0, 8),
      adjacentCollapsibleCount: adjacentCollapsibles.length,
      adjacentCollapsiblesSpaced: gaps.every((gap) => gap >= 10),
      gaps,
      roundedCollapsiblesClip: [...document.querySelectorAll('details.collapsible:not(.collapsible--sm)')]
        .every((panel) => getComputedStyle(panel).overflow !== 'visible')
    };
  })()`);
}

async function measureAccessMatrixLayout() {
  return evaluate(`(() => {
    const table = document.querySelector('table.data[data-table-key="system-capabilities"]');
    const wrap = table?.closest('.table-wrap');
    const row = table?.tBodies[0]?.rows[0];
    if (!table || !wrap || !row) return null;
    const firstCell = row.cells[0];
    const badge = row.querySelector('.badge');
    const firstCellStyle = getComputedStyle(firstCell);
    const badgeRect = badge?.getBoundingClientRect();
    const cells = [...row.cells];
    return {
      firstColumnSticky: firstCellStyle.position === 'sticky',
      tableLayoutAuto: getComputedStyle(table).tableLayout === 'auto',
      rowCellsAligned: cells.every((cell) => Math.abs(cell.getBoundingClientRect().top - row.getBoundingClientRect().top) <= 1),
      badgeInsideCell: !badgeRect || cells.slice(1).some((cell) => {
        const rect = cell.getBoundingClientRect();
        return badgeRect.left >= rect.left - 1 && badgeRect.right <= rect.right + 1 &&
          badgeRect.top >= rect.top - 1 && badgeRect.bottom <= rect.bottom + 1;
      }),
      wrappedInOwnScroller: wrap.scrollWidth > wrap.clientWidth
    };
  })()`);
}

async function measureSharedTableStyles(name) {
  return evaluate(`(() => {
    const table = document.querySelector('table.data');
    const wrap = table?.closest('.table-wrap');
    const header = table?.tHead?.querySelector('th');
    const row = table?.tBodies[0]?.rows[0];
    const cell = row?.cells[0];
    if (!wrap || !table || !header || !cell) return null;
    const root = getComputedStyle(document.documentElement);
    const headerStyle = getComputedStyle(header);
    const rowStyle = getComputedStyle(row);
    const cellStyle = getComputedStyle(cell);
    const tableStyle = getComputedStyle(table);
    const token = (name) => root.getPropertyValue(name).trim();
    const colorToken = (name) => {
      const probe = document.createElement('span');
      probe.style.color = token(name);
      document.body.appendChild(probe);
      const value = getComputedStyle(probe).color;
      probe.remove();
      return value;
    };
    const compactResponsive = table.classList.contains('data--responsive') && innerWidth <= 900;
    return {
      key: table.dataset.tableKey || null,
      className: table.className,
      hasForbiddenModifier: [...table.classList].some((className) =>
        /^data--(journal|tasks|users|events|exchange|reports|protocol|capabilities|letter|wide)$/.test(className)
      ),
      compactResponsive,
      headerBgMatches: compactResponsive || headerStyle.backgroundColor === colorToken('--table-header-bg'),
      headerTextMatches: compactResponsive || headerStyle.color === colorToken('--table-text'),
      rowBgMatches: compactResponsive || rowStyle.backgroundColor === colorToken('--table-row-bg'),
      cellTextMatches: compactResponsive || cellStyle.color === colorToken('--table-text'),
      borderMatches: compactResponsive || cellStyle.borderBottomColor === colorToken('--table-border') ||
        cellStyle.borderBottomStyle === 'none' || cellStyle.borderBottomWidth === '0px',
      tableBgMatches: tableStyle.backgroundColor === colorToken('--table-bg'),
      rowHeight: Math.round(cell.getBoundingClientRect().height),
      expectedRowHeight: parseInt(token('--table-row-height'), 10),
      headerHeight: Math.round(header.getBoundingClientRect().height),
      expectedHeaderHeight: parseInt(token('--table-header-height'), 10),
      paddingX: cellStyle.paddingLeft,
      expectedPaddingX: token('--table-cell-padding-x'),
      inspectedRoute: ${JSON.stringify(name)}
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
  for (const [theme, font, contrast] of accessibilityModes) {
    for (const [width, height] of sampledModeViewports) {
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
      metrics.collapsibleLayout = await measureCollapsibleLayout();
      metrics.formContainment = await measureFormContainment();
      metrics.accessMatrixLayout = name === "user-form" ? await measureAccessMatrixLayout() : null;
      metrics.responsiveTable = responsiveRouteNames.has(name) ? await measureResponsiveTable() : null;
      metrics.sharedTableStyles = await measureSharedTableStyles(name);
      metrics.browserErrors = browserErrors.slice(errorStart);
      const shot = await command("Page.captureScreenshot", { format: "png", fromSurface: true });
      const filename = `${name}-${width}x${height}-light.png`;
      await writeFile(join(outputDir, filename), Buffer.from(shot.data, "base64"));
      results.push({ name, viewport: `${width}x${height}`, theme: "light", font: "base", ...metrics, screenshot: filename });
    }
  }

  for (const [theme, font, contrast] of accessibilityModes) {
    for (const [width, height] of sampledModeViewports) {
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
        metrics.collapsibleLayout = await measureCollapsibleLayout();
        metrics.formContainment = await measureFormContainment();
        metrics.accessMatrixLayout = name === "user-form" ? await measureAccessMatrixLayout() : null;
        metrics.responsiveTable = responsiveRouteNames.has(name) ? await measureResponsiveTable() : null;
        metrics.sharedTableStyles = await measureSharedTableStyles(name);
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
    await evaluate(`document.documentElement.dataset.theme='light'; document.documentElement.dataset.font='base'; document.documentElement.dataset.contrast='default'`);
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
        appliedMode: {
          theme: document.documentElement.dataset.theme || null,
          font: document.documentElement.dataset.font || null,
          contrast: document.documentElement.dataset.contrast || null
        },
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
    expectedStatus: expectedStatuses.get(item.name) ||
      (expectedForbidden.has(item.name) ? 403 : 200),
    modeMismatch: item.appliedMode.theme !== item.theme ||
      item.appliedMode.font !== item.font ||
      item.appliedMode.contrast !== (item.contrast || "default"),
    journalLayoutMismatch: !expectedForbidden.has(item.name) && !expectedStatuses.has(item.name) &&
      item.name === "journal" && item.width >= 1024 && (!item.journalLayout ||
      !item.journalLayout.groupRowsRemoved ||
      !item.journalLayout.statusPinned ||
      !item.journalLayout.sortIndicatorsVisible),
    taskLayoutMismatch: !expectedForbidden.has(item.name) && !expectedStatuses.has(item.name) &&
      item.name === "tasks" && [1280, 1366].includes(item.width) &&
      (!item.taskLayout || !item.taskLayout.actionCellSticky ||
        !item.taskLayout.actionsVisible || item.taskLayout.compact),
    responsiveTableMismatch: !expectedForbidden.has(item.name) && !expectedStatuses.has(item.name) &&
      responsiveRouteNames.has(item.name) && item.width <= 900 &&
      (!item.responsiveTable || !item.responsiveTable.compact ||
        !item.responsiveTable.headerHidden || !item.responsiveTable.cardGrid ||
        item.responsiveTable.horizontallyScrollable || !item.responsiveTable.actionsVisible),
    sharedTableStyleMismatch: !expectedForbidden.has(item.name) && !expectedStatuses.has(item.name) &&
      item.sharedTableStyles && (item.sharedTableStyles.hasForbiddenModifier ||
        !item.sharedTableStyles.headerBgMatches || !item.sharedTableStyles.headerTextMatches ||
        !item.sharedTableStyles.rowBgMatches || !item.sharedTableStyles.cellTextMatches ||
        !item.sharedTableStyles.borderMatches || !item.sharedTableStyles.tableBgMatches ||
        (!item.sharedTableStyles.compactResponsive &&
          item.sharedTableStyles.rowHeight < item.sharedTableStyles.expectedRowHeight) ||
        (!item.sharedTableStyles.compactResponsive &&
          item.sharedTableStyles.headerHeight < item.sharedTableStyles.expectedHeaderHeight) ||
        (!item.sharedTableStyles.compactResponsive &&
          item.sharedTableStyles.paddingX !== item.sharedTableStyles.expectedPaddingX)),
    collapsibleLayoutMismatch: !expectedForbidden.has(item.name) && !expectedStatuses.has(item.name) &&
      item.collapsibleLayout && (!item.collapsibleLayout.closed ||
        !item.collapsibleLayout.hasBorder || !item.collapsibleLayout.clipsRoundedHeader ||
        !item.collapsibleLayout.hasLeftStateBar ||
        !item.collapsibleLayout.hasStateText || !item.collapsibleLayout.minTapHeight),
    formContainmentMismatch: !expectedForbidden.has(item.name) && !expectedStatuses.has(item.name) &&
      item.formContainment && (item.formContainment.overflowCount > 0 ||
        !item.formContainment.roundedCollapsiblesClip ||
        (item.formContainment.adjacentCollapsibleCount > 0 &&
          !item.formContainment.adjacentCollapsiblesSpaced)),
    accessMatrixLayoutMismatch: !expectedForbidden.has(item.name) && !expectedStatuses.has(item.name) &&
      item.name === "user-form" && item.width >= 1024 && (!item.accessMatrixLayout ||
        !item.accessMatrixLayout.firstColumnSticky || !item.accessMatrixLayout.tableLayoutAuto ||
        !item.accessMatrixLayout.rowCellsAligned || !item.accessMatrixLayout.badgeInsideCell ||
        !item.accessMatrixLayout.wrappedInOwnScroller),
    printLayoutMismatch: item.name.startsWith("print-") && (!item.printLayout ||
      !item.printLayout.screenControlsHidden || !item.printLayout.sheetReset ||
      !item.printLayout.tableHeadersStatic || !item.printLayout.letterRowsNeutral),
  }));
  const report = {
    generatedAt: new Date().toISOString(),
    baseUrl,
    cases: results.length,
    expectedForbidden: [...expectedForbidden],
    expectedStatuses: Object.fromEntries(expectedStatuses),
    failures: checkedResults.filter((item) =>
      item.documentOverflow || (item.width >= 1024 && item.navOverflow) ||
      (item.name !== "login" && item.path.includes("login")) ||
      item.httpStatus !== item.expectedStatus ||
      item.forbidden !== item.expectedForbidden || item.browserErrors.length || item.modeMismatch ||
      item.journalLayoutMismatch || item.taskLayoutMismatch || item.responsiveTableMismatch ||
      item.sharedTableStyleMismatch || item.collapsibleLayoutMismatch ||
      item.formContainmentMismatch || item.accessMatrixLayoutMismatch ||
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
