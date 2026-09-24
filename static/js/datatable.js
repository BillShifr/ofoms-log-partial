// Единый компонент DataTable: клик по всей строке, сортировка, тултипы, resize.
// Разметка: table.data[data-client-sort] — сортировка по th без вложенных ссылок;
// tr[data-href] — переход по строке; [data-tip] — кастомный тултип.
(function () {
  var dynamicSheets = {};

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
      th.classList.toggle('sort-asc', th.getAttribute('aria-sort') === 'ascending');
      th.classList.toggle('sort-desc', th.getAttribute('aria-sort') === 'descending');
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
        th.addEventListener('click', function (event) {
          if (event.target.closest('.col-resizer')) return;
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

  function widthStyleId(key) {
    var value = String(key);
    var hash = 0;
    for (var index = 0; index < value.length; index += 1) {
      hash = ((hash << 5) - hash + value.charCodeAt(index)) | 0;
    }
    return 'datatable-widths-' + Math.abs(hash);
  }

  function setDynamicRules(id, rules) {
    if ('adoptedStyleSheets' in document && typeof CSSStyleSheet === 'function') {
      if (!dynamicSheets[id]) {
        dynamicSheets[id] = new CSSStyleSheet();
        document.adoptedStyleSheets = Array.prototype.concat.call(
          document.adoptedStyleSheets,
          dynamicSheets[id]
        );
      }
      dynamicSheets[id].replaceSync(rules.join('\n'));
      return;
    }
    var style = document.getElementById(id);
    if (!style) {
      style = document.createElement('style');
      style.id = id;
      document.head.appendChild(style);
    }
    style.textContent = rules.join('\n');
  }

  function clearDynamicRules(id) {
    if (dynamicSheets[id]) {
      document.adoptedStyleSheets = Array.prototype.filter.call(
        document.adoptedStyleSheets,
        function (sheet) { return sheet !== dynamicSheets[id]; }
      );
      delete dynamicSheets[id];
    }
    var style = document.getElementById(id);
    if (style) style.remove();
  }

  function syncWidthRules(table, widths) {
    var key = table.getAttribute('data-table-key') || location.pathname;
    var styleId = widthStyleId(key);
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
    setDynamicRules(styleId, rules);
  }

  function clearWidthRules(tableKey) {
    clearDynamicRules(widthStyleId(tableKey || location.pathname));
  }

  function indexColumns(table) {
    var headerRow = table.tHead && table.tHead.rows[table.tHead.rows.length - 1];
    var columnCount = headerRow ? headerRow.cells.length : 0;
    var colgroup = table.querySelector('colgroup');
    if (!colgroup && columnCount) {
      colgroup = document.createElement('colgroup');
      for (var created = 0; created < columnCount; created += 1) {
        colgroup.appendChild(document.createElement('col'));
      }
      table.insertBefore(colgroup, table.firstChild);
    } else if (colgroup && columnCount) {
      while (colgroup.children.length < columnCount) {
        colgroup.appendChild(document.createElement('col'));
      }
    }
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

  function refreshPinnedOffsets(table) {
    var headerRow = table.tHead && table.tHead.rows[table.tHead.rows.length - 1];
    if (!headerRow) return;
    var key = table.getAttribute('data-table-key') || location.pathname;
    var styleId = widthStyleId('pinned:' + key);
    var left = 0;
    var rules = [];
    Array.prototype.forEach.call(headerRow.cells, function (header, index) {
      if (!header.classList.contains('data-pinned')) return;
      var selector = 'table.data[data-table-key="' + attrValue(key) + '"] tr:not(.column-group-row) > .data-pinned:nth-child(' + (index + 1) + ')';
      rules.push(selector + '{--pinned-left:' + left + 'px;}');
      left += header.getBoundingClientRect().width;
    });
    setDynamicRules(styleId, rules);
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
        function stopResizeEvent(event) {
          event.preventDefault();
          event.stopPropagation();
          if (event.stopImmediatePropagation) event.stopImmediatePropagation();
        }
        function persist(width) {
          widths[index] = setColumnWidth(table, index, width);
          widths.__table = Array.prototype.reduce.call(headerRow.cells, function (sum, cell, cellIndex) {
            return sum + (cellIndex === index ? widths[index] : cell.getBoundingClientRect().width);
          }, 0);
          syncWidthRules(table, widths);
          writeWidths(table, widths);
          refreshPinnedOffsets(table);
          document.querySelectorAll('table.data td.cell-long').forEach(function (td) {
            td.dispatchEvent(new Event('datatable:resize'));
          });
        }
        grip.addEventListener('pointerdown', function (event) {
          stopResizeEvent(event);
          startX = event.clientX;
          startWidth = th.getBoundingClientRect().width;
          table.classList.add('is-resizing-columns');
          grip.classList.add('is-resizing');
          grip.setPointerCapture(event.pointerId);
        });
        grip.addEventListener('pointermove', function (event) {
          if (!grip.hasPointerCapture(event.pointerId)) return;
          stopResizeEvent(event);
          persist(startWidth + event.clientX - startX);
        });
        grip.addEventListener('pointerup', function (event) {
          stopResizeEvent(event);
          if (grip.hasPointerCapture(event.pointerId)) grip.releasePointerCapture(event.pointerId);
          table.classList.remove('is-resizing-columns');
          grip.classList.remove('is-resizing');
        });
        grip.addEventListener('pointercancel', function (event) {
          stopResizeEvent(event);
          if (grip.hasPointerCapture(event.pointerId)) grip.releasePointerCapture(event.pointerId);
          table.classList.remove('is-resizing-columns');
          grip.classList.remove('is-resizing');
        });
        grip.addEventListener('click', function (event) {
          stopResizeEvent(event);
        });
        grip.addEventListener('keydown', function (event) {
          if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
          event.preventDefault();
          persist(th.getBoundingClientRect().width + (event.key === 'ArrowRight' ? 16 : -16));
        });
      });
      refreshPinnedOffsets(table);
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
            ensureDialogNames();
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
      var error = form.querySelector('[data-table-prefs-error]');
      if (!form.querySelector('input[name="columns"]:checked')) {
        if (error) {
          error.textContent = 'Оставьте видимой хотя бы одну колонку.';
          error.hidden = false;
        }
        return;
      }
      if (error) error.hidden = true;
      fetch(form.action, {
        method: 'POST',
        body: new FormData(form),
        credentials: 'same-origin',
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      })
        .then(function (response) {
          if (!response.ok) {
            return response.json().catch(function () { return {}; }).then(function (payload) {
              throw new Error(payload.error || 'Не удалось сохранить настройки.');
            });
          }
          var dialog = form.closest('dialog');
          if (dialog && typeof dialog.close === 'function') dialog.close();
          if (window.portalNavigate) return window.portalNavigate(window.location.href, {
            history: 'replace', preserveScroll: true
          });
          window.location.reload();
        })
        .catch(function (requestError) {
          if (error) {
            error.textContent = requestError.message;
            error.hidden = false;
          }
        });
    });

    document.addEventListener('click', function (event) {
      var reset = event.target.closest('[data-table-reset-widths]');
      if (!reset) return;
      var tableKey = reset.getAttribute('data-table-key');
      try { localStorage.removeItem(storageKeyByName(tableKey)); }
      catch (e) {}
      clearWidthRules(tableKey);
      if (window.portalNavigate) {
        window.portalNavigate(window.location.href, { history: 'replace', preserveScroll: true });
      } else {
        window.location.reload();
      }
    });

    document.addEventListener('click', function (event) {
      var selectAll = event.target.closest('[data-table-select-all]');
      if (!selectAll) return;
      var form = selectAll.closest('form');
      if (!form) return;
      form.querySelectorAll('input[name="columns"]').forEach(function (checkbox) {
        checkbox.checked = true;
      });
      var error = form.querySelector('[data-table-prefs-error]');
      if (error) error.hidden = true;
    });
  }

  function applyTablePreferences(table, payload) {
    if (!payload || !payload.columns) return;
    var keys = payload.columns.map(function (column) { return column.key; });
    var selected = payload.current && payload.current.length ? payload.current : keys;
    var selectedSet = new Set(selected);
    var orderedKeys = selected.concat(keys.filter(function (key) {
      return selected.indexOf(key) === -1;
    }));
    var serverManaged = table.dataset.tableServerManaged === 'true';

    if (!serverManaged) {
      Array.prototype.forEach.call(table.rows, function (row) {
        if (row.classList.contains('column-group-row')) return;
        if (row.cells.length !== keys.length || row.querySelector('[colspan]')) return;
        var byKey = {};
        Array.prototype.forEach.call(row.cells, function (cell, index) {
          var key = cell.dataset.columnKey || keys[index];
          cell.dataset.columnKey = key;
          byKey[key] = cell;
        });
        orderedKeys.forEach(function (key) {
          var cell = byKey[key];
          if (!cell) return;
          cell.hidden = !selectedSet.has(key);
          row.appendChild(cell);
        });
      });
    }
    if (serverManaged) {
      Array.prototype.forEach.call(table.rows, function (row) {
        if (row.classList.contains('column-group-row') || row.querySelector('[colspan]')) return;
        Array.prototype.forEach.call(row.cells, function (cell, index) {
          if (selected[index]) cell.dataset.columnKey = selected[index];
        });
      });
    }
    table.querySelectorAll('tr [colspan]').forEach(function (cell) {
      cell.colSpan = selected.length;
    });
    table.classList.remove('th-sticky');

    var oldGroupRow = table.tHead && table.tHead.querySelector('.column-group-row');
    if (oldGroupRow) oldGroupRow.remove();
    var groupedHeaders = new Set(payload.grouped_headers || []);
    if (table.tHead && groupedHeaders.size) {
      var groupByKey = {};
      payload.columns.forEach(function (column) { groupByKey[column.key] = column.group || ''; });
      var groupRow = document.createElement('tr');
      groupRow.className = 'column-group-row';
      var segments = [];
      selected.forEach(function (key) {
        var group = groupedHeaders.has(groupByKey[key]) ? groupByKey[key] : '';
        var last = segments[segments.length - 1];
        if (last && last.label === group) last.span += 1;
        else segments.push({ label: group, span: 1 });
      });
      segments.forEach(function (segment) {
        var th = document.createElement('th');
        th.scope = 'colgroup';
        th.colSpan = segment.span;
        th.textContent = segment.label;
        if (!segment.label) th.className = 'column-group-row__empty';
        groupRow.appendChild(th);
      });
      table.tHead.insertBefore(groupRow, table.tHead.firstChild);
    }

    var pinned = payload.pinned_columns || [];
    if (!pinned.length && payload.fixed_first && selected.length) pinned = [selected[0]];
    var pinnedSet = new Set(pinned.filter(function (key) { return selectedSet.has(key); }));
    var headerRow = table.tHead && table.tHead.rows[table.tHead.rows.length - 1];
    if (headerRow) {
      Array.prototype.forEach.call(headerRow.cells, function (header, index) {
        var key = header.dataset.columnKey || selected[index];
        var isPinned = pinnedSet.has(key);
        Array.prototype.forEach.call(table.rows, function (row) {
          if (row.classList.contains('column-group-row') || !row.cells[index]) return;
          row.cells[index].classList.toggle('data-pinned', isPinned);
        });
      });
    }
    refreshPinnedOffsets(table);

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

  function ensureDialogNames() {
    document.querySelectorAll('dialog.modal').forEach(function (dialog, index) {
      if (dialog.hasAttribute('aria-label') || dialog.hasAttribute('aria-labelledby')) return;
      var heading = dialog.querySelector('h1, h2, h3');
      if (!heading) return;
      if (!heading.id) heading.id = (dialog.id || 'dialog-' + index) + '-title';
      dialog.setAttribute('aria-labelledby', heading.id);
    });
  }

  function initEventDetails() {
    document.querySelectorAll('.event-detail-toggle').forEach(function (button) {
      if (button.dataset.detailReady === 'true') return;
      button.dataset.detailReady = 'true';
      button.addEventListener('click', function () {
        var detail = document.getElementById(button.getAttribute('aria-controls'));
        if (!detail) return;
        var expanded = button.getAttribute('aria-expanded') === 'true';
        button.setAttribute('aria-expanded', String(!expanded));
        detail.hidden = expanded;
        var label = button.querySelector('.sr-only');
        if (label) label.textContent = expanded ? ': показать детали события' : ': скрыть детали события';
      });
    });
  }

  function initContent() {
    initSort();
    initTooltips();
    initCellTruncate();
    ensureDialogNames();
    initEventDetails();
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
