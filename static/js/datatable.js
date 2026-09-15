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
      window.location.href = el.getAttribute('data-href');
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
      Array.prototype.forEach.call(table.tHead.rows[table.tHead.rows.length - 1].cells, function (th, i) {
        if (th.hasAttribute('data-no-sort') || isInteractive(th) || th.querySelector('a')) return;
        th.classList.add('data-sort');
        th.tabIndex = 0;
        th.setAttribute('aria-sort', 'none');
        th.setAttribute('aria-label', th.textContent.trim() + ': сортировать');
        th.addEventListener('click', function () { sortTable(table, i); });
        th.addEventListener('keydown', function (event) {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            sortTable(table, i);
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

  document.addEventListener('DOMContentLoaded', function () {
    initRowClick();
    initSort();
    initTooltips();
    initCellTruncate();
    initResize();
  });
})();
