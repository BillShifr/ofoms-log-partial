// Единый компонент DataTable: клик по всей строке, сортировка, тултипы, resize.
// Разметка: table.data[data-client-sort] — сортировка по th без вложенных ссылок;
// tr[data-href] — переход по строке; [data-tip] — кастомный тултип.
(function () {
  function isInteractive(el) {
    return el && (el.closest('a, button, input, select, textarea, form, label') !== null);
  }

  function initRowClick() {
    document.addEventListener('click', function (e) {
      var el = e.target.closest('[data-href]');
      if (!el || isInteractive(e.target)) return;
      e.preventDefault();
      var href = el.getAttribute('data-href');
      if (window.portalNavigate) window.portalNavigate(href, { history: 'push', preserveScroll: false });
      else window.location.href = href;
    });
  }

  function sortTable(table, index) {
    var tbody = table.tBodies[0];
    var th = table.tHead.rows[table.tHead.rows.length - 1].cells[index];
    var type = th.getAttribute('data-type') || '';
    var numeric = type === 'num' || type === 'date';
    var key = function (row) {
      var td = row ? row.cells[index] : null;
      var valueNode = td ? td.querySelector('[data-value]') : null;
      var v = td ? td.getAttribute('data-value') : null;
      if (v === null && valueNode) v = valueNode.getAttribute('data-value');
      if (v === null) v = td ? td.textContent.trim() : '';
      return numeric ? parseFloat(v) : v.toLowerCase();
    };
    var head = th.getAttribute('data-sort-state') || 'none';
    var dir = head === 'asc' ? 'desc' : 'asc';
    var groups = [];
    var byId = {};
    Array.prototype.forEach.call(tbody.rows, function (row, rowIndex) {
      var id = row.getAttribute('data-sort-group') || '__row_' + rowIndex;
      if (!byId[id]) {
        byId[id] = { rows: [], value: key(row) };
        groups.push(byId[id]);
      }
      byId[id].rows.push(row);
    });
    groups.sort(function (a, b) {
      var av = a.value, bv = b.value;
      if (numeric) {
        if (Number.isNaN(av)) return 1;
        if (Number.isNaN(bv)) return -1;
        return dir === 'asc' ? av - bv : bv - av;
      }
      return dir === 'asc' ? String(av).localeCompare(String(bv), 'ru') : String(bv).localeCompare(String(av), 'ru');
    });
    groups.forEach(function (group) {
      group.rows.forEach(function (row) { tbody.appendChild(row); });
    });
    Array.prototype.forEach.call(table.tHead.rows[table.tHead.rows.length - 1].cells, function (c) {
      c.classList.remove('sort-asc', 'sort-desc');
      delete c.dataset.sortState;
      if (c.classList.contains('data-sort')) c.setAttribute('aria-sort', 'none');
    });
    th.classList.add(dir === 'asc' ? 'sort-asc' : 'sort-desc');
    th.dataset.sortState = dir;
    th.setAttribute('aria-sort', dir === 'asc' ? 'ascending' : 'descending');
  }

  function initSort() {
    document.querySelectorAll('table.data th[aria-sort]').forEach(function (th) {
      th.classList.add('data-sort');
      var link = th.querySelector('a');
      if (link && !link.getAttribute('aria-label')) {
        link.setAttribute('aria-label', th.textContent.trim() + ': сортировать');
      }
    });
    document.querySelectorAll('table.data[data-client-sort]').forEach(function (table) {
      if (table.dataset.sortReady === 'true') return;
      table.dataset.sortReady = 'true';
      Array.prototype.forEach.call(table.tHead.rows[table.tHead.rows.length - 1].cells, function (th, i) {
        if (th.hasAttribute('data-no-sort') || isInteractive(th) || th.querySelector('a')) return;
        th.classList.add('data-sort');
        th.tabIndex = 0;
        th.setAttribute('aria-sort', 'none');
        th.setAttribute('aria-label', th.textContent.trim() + ': сортировать');
        th.addEventListener('click', function () {
          sortTable(table, Array.prototype.indexOf.call(th.parentNode.cells, th));
        });
        th.addEventListener('keydown', function (event) {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            sortTable(table, Array.prototype.indexOf.call(th.parentNode.cells, th));
          }
        });
      });
    });
  }

  function initTooltips() {
    document.querySelectorAll('[data-tip]').forEach(function (element) {
      if (!element.hasAttribute('title')) {
        element.setAttribute('title', element.getAttribute('data-tip'));
      }
    });
  }

  function initCellTruncate() {
    function hasOverflow(element) {
      return element.scrollWidth > element.clientWidth || element.scrollHeight > element.clientHeight;
    }

    function syncOverflowTip(td) {
      var measure = td.querySelector('.cell-clip') || td;
      if (!td.dataset.overflowTip) {
        td.dataset.overflowTip = (td.getAttribute('title') || td.textContent || '').trim();
      }
      var tip = td.dataset.overflowTip;
      var overflowing = tip && hasOverflow(measure);
      if (overflowing) {
        td.setAttribute('title', tip);
        if (!isInteractive(td) && !td.hasAttribute('tabindex')) {
          td.tabIndex = 0;
          td.dataset.overflowManagedFocus = 'true';
        }
      } else {
        td.removeAttribute('title');
        if (td.dataset.overflowManagedFocus === 'true') td.removeAttribute('tabindex');
      }
    }

    document.querySelectorAll('table.data td.cell-long').forEach(function (td) {
      if (td.dataset.truncateReady === 'true') return;
      td.dataset.truncateReady = 'true';
      syncOverflowTip(td);
      td.addEventListener('datatable:resize', function () { syncOverflowTip(td); });
      if (window.ResizeObserver) {
        var observer = new ResizeObserver(function () { syncOverflowTip(td); });
        observer.observe(td);
      } else {
        window.addEventListener('resize', function () { syncOverflowTip(td); });
      }
    });
  }

  function storageKey(table) {
    return 'datatable-widths:' + (table.getAttribute('data-table-key') || location.pathname);
  }

  function storageKeyByName(tableKey) {
    return 'datatable-widths:' + (tableKey || location.pathname);
  }

  function readWidths(table) {
    try { return JSON.parse(localStorage.getItem(storageKey(table)) || '{}'); }
    catch (e) { return {}; }
  }

  function writeWidths(table, widths) {
    try { localStorage.setItem(storageKey(table), JSON.stringify(widths)); }
    catch (e) {}
  }

  function attrValue(value) {
    return String(value).replace(/\\/g, '\\\\').replace(/"/g, '\\"');
  }

  function syncWidthRules(table, widths) {
    var key = table.getAttribute('data-table-key') || location.pathname;
    var sheet = Array.prototype.find.call(document.styleSheets, function (candidate) {
      return candidate.href && candidate.href.indexOf('/static/css/portal.css') !== -1;
    }) || document.styleSheets[0];
    if (!sheet) return;
    var rules = [];
    Object.keys(widths).forEach(function (index) {
      if (index === '__table') return;
      var width = Math.max(56, Math.round(Number(widths[index]) || 0));
      if (!width) return;
      var selector = 'table.data[data-table-key="' + attrValue(key) + '"] [data-col-index="' + attrValue(index) + '"]';
      rules.push(selector + '{width:' + width + 'px;min-width:' + width + 'px;max-width:' + width + 'px;}');
    });
    if (widths.__table) {
      var tableSelector = 'table.data[data-table-key="' + attrValue(key) + '"]';
      var tableWidth = Math.max(table.getBoundingClientRect().width, Math.round(Number(widths.__table) || 0));
      rules.push(tableSelector + '{width:' + tableWidth + 'px;min-width:' + tableWidth + 'px;}');
    }
    rules.forEach(function (rule) {
      try {
        sheet.insertRule(rule, sheet.cssRules.length);
      } catch (e) {}
    });
  }

  function indexColumns(table) {
    var cols = table.querySelectorAll('colgroup col');
    Array.prototype.forEach.call(cols, function (col, index) {
      col.setAttribute('data-col-index', String(index));
    });
    Array.prototype.forEach.call(table.rows, function (row) {
      Array.prototype.forEach.call(row.cells, function (cell, index) {
        if (!cell.hasAttribute('colspan')) cell.setAttribute('data-col-index', String(index));
      });
    });
  }

  function setColumnWidth(table, index, width) {
    var clamped = Math.max(56, Math.round(width));
    return clamped;
  }

  function initResize() {
    document.querySelectorAll('table.data[data-table-key]').forEach(function (table) {
      if (table.getAttribute('data-table-key') === 'system-capabilities') return;
      if (table.dataset.resizeReady === 'true') return;
      table.dataset.resizeReady = 'true';
      var headerRow = table.tHead && table.tHead.rows[table.tHead.rows.length - 1];
      if (!headerRow) return;
      indexColumns(table);
      var widths = readWidths(table);
      syncWidthRules(table, widths);
      Array.prototype.forEach.call(headerRow.cells, function (th, index) {
        var grip = document.createElement('button');
        grip.type = 'button';
        grip.className = 'col-resizer';
        grip.setAttribute('aria-label', 'Изменить ширину колонки ' + th.textContent.trim());
        grip.setAttribute('title', 'Изменить ширину колонки');
        th.appendChild(grip);

        var startX = 0;
        var startWidth = 0;
        function persist(width) {
          widths[index] = setColumnWidth(table, index, width);
          widths.__table = Array.prototype.reduce.call(headerRow.cells, function (sum, cell, cellIndex) {
            return sum + (cellIndex === index ? widths[index] : cell.getBoundingClientRect().width);
          }, 0);
          syncWidthRules(table, widths);
          writeWidths(table, widths);
          document.querySelectorAll('table.data td.cell-long').forEach(function (td) {
            td.dispatchEvent(new Event('datatable:resize'));
          });
        }
        grip.addEventListener('pointerdown', function (event) {
          event.preventDefault();
          startX = event.clientX;
          startWidth = th.getBoundingClientRect().width;
          grip.setPointerCapture(event.pointerId);
        });
        grip.addEventListener('pointermove', function (event) {
          if (!grip.hasPointerCapture(event.pointerId)) return;
          persist(startWidth + event.clientX - startX);
        });
        grip.addEventListener('pointerup', function (event) {
          if (grip.hasPointerCapture(event.pointerId)) grip.releasePointerCapture(event.pointerId);
        });
        grip.addEventListener('keydown', function (event) {
          if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
          event.preventDefault();
          persist(th.getBoundingClientRect().width + (event.key === 'ArrowRight' ? 16 : -16));
        });
      });
    });
  }

  function initTableSettings() {
    document.addEventListener('click', function (event) {
      var trigger = event.target.closest('[data-table-settings-trigger]');
      if (!trigger) return;
      var dialog = document.getElementById(trigger.getAttribute('data-modal-target'));
      if (!dialog) return;
      event.preventDefault();
      var content = dialog.querySelector('[data-table-settings-content]');
      var settingsUrl = trigger.getAttribute('data-settings-url');
      if (content && settingsUrl && !content.dataset.loaded) {
        var url = settingsUrl + (settingsUrl.indexOf('?') === -1 ? '?' : '&') + 'modal=1';
        fetch(url, { credentials: 'same-origin' })
          .then(function (response) { return response.text(); })
          .then(function (html) {
            content.innerHTML = html;
            content.dataset.loaded = 'true';
          })
          .catch(function () {
            content.innerHTML = '<p class="alert alert--error">Не удалось загрузить настройки колонок.</p>';
          });
      }
      if (typeof dialog.showModal === 'function') {
        dialog.showModal();
      } else {
        dialog.setAttribute('open', 'open');
      }
    });

    document.addEventListener('submit', function (event) {
      var form = event.target.closest('[data-table-prefs-form]');
      if (!form) return;
      event.preventDefault();
      fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      })
        .then(function (response) {
          if (!response.ok) throw new Error('save failed');
          var dialog = form.closest('dialog');
          if (dialog && typeof dialog.close === 'function') dialog.close();
          if (window.portalNavigate) return window.portalNavigate(window.location.href, {
            history: 'replace', preserveScroll: true
          });
          window.location.reload();
        })
        .catch(function () {
          var error = form.querySelector('[data-table-prefs-error]');
          if (error) error.hidden = false;
        });
    });

    document.addEventListener('click', function (event) {
      var reset = event.target.closest('[data-table-reset-widths]');
      if (!reset) return;
      try { localStorage.removeItem(storageKeyByName(reset.getAttribute('data-table-key'))); }
      catch (e) {}
      if (window.portalNavigate) {
        window.portalNavigate(window.location.href, { history: 'replace', preserveScroll: true });
      } else {
        window.location.reload();
      }
    });
  }

  function applyTablePreferences(table, payload) {
    if (!payload || !payload.columns || table.dataset.tableServerManaged === 'true') return;
    var keys = payload.columns.map(function (column) { return column.key; });
    var selected = payload.current && payload.current.length ? payload.current : keys;
    var selectedSet = new Set(selected);
    var orderedKeys = selected.concat(keys.filter(function (key) {
      return selected.indexOf(key) === -1;
    }));

    Array.prototype.forEach.call(table.rows, function (row) {
      if (row.cells.length !== keys.length || row.querySelector('[colspan]')) return;
      var byKey = {};
      Array.prototype.forEach.call(row.cells, function (cell, index) {
        byKey[keys[index]] = cell;
      });
      orderedKeys.forEach(function (key) {
        var cell = byKey[key];
        if (!cell) return;
        cell.hidden = !selectedSet.has(key);
        row.appendChild(cell);
      });
    });
    table.querySelectorAll('tr [colspan]').forEach(function (cell) {
      cell.colSpan = selected.length;
    });
    table.classList.toggle('th-sticky', Boolean(payload.fixed_first));

    var sorting = payload.sorting || {};
    if (sorting.field && table.hasAttribute('data-client-sort')) {
      var index = selected.indexOf(sorting.field);
      if (index !== -1) {
        sortTable(table, index);
        if (sorting.dir === '-') sortTable(table, index);
      }
    }
  }

  function initTablePreferences() {
    var requests = Array.prototype.map.call(
      document.querySelectorAll('table.data[data-table-settings-url]'),
      function (table) {
        if (table.dataset.tableServerManaged === 'true') return Promise.resolve();
        var url = table.dataset.tableSettingsUrl;
        url += (url.indexOf('?') === -1 ? '?' : '&') + 'format=json';
        return fetch(url, { credentials: 'same-origin' })
          .then(function (response) {
            if (!response.ok) throw new Error('preferences unavailable');
            return response.json();
          })
          .then(function (payload) { applyTablePreferences(table, payload); })
          .catch(function () { return null; });
      }
    );
    return Promise.all(requests);
  }

  function initDialogs() {
    document.addEventListener('click', function (event) {
      var close = event.target.closest('[data-modal-close]');
      if (close) {
        var currentDialog = close.closest('dialog');
        if (currentDialog && typeof currentDialog.close === 'function') currentDialog.close();
        return;
      }
      var trigger = event.target.closest('[data-modal-open]');
      if (!trigger) return;
      var dialog = document.getElementById(trigger.getAttribute('data-modal-open'));
      if (!dialog) return;
      event.preventDefault();
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', 'open');
    });
  }

  function initContent() {
    initSort();
    initTooltips();
    initCellTruncate();
    initTablePreferences().then(initResize);
  }

  document.addEventListener('DOMContentLoaded', function () {
    initRowClick();
    initContent();
    initTableSettings();
    initDialogs();
  });
  document.addEventListener('portal:render', initContent);
})();
