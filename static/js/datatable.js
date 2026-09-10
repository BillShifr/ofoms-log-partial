// Единый компонент DataTable: клик по всей строке, сортировка, тултипы.
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
    var th = table.tHead.rows[0].cells[index];
    var numeric = th.getAttribute('data-type') === 'num';
    var key = function (row) {
      var td = row ? row.cells[index] : null;
      var v = td ? td.getAttribute('data-value') : null;
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
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (c) {
      c.classList.remove('sort-asc', 'sort-desc');
      delete c.dataset.sortState;
      if (c.classList.contains('data-sort')) c.setAttribute('aria-sort', 'none');
    });
    th.classList.add(dir === 'asc' ? 'sort-asc' : 'sort-desc');
    th.dataset.sortState = dir;
    th.setAttribute('aria-sort', dir === 'asc' ? 'ascending' : 'descending');
  }

  function initSort() {
    document.querySelectorAll('table.data[data-client-sort]').forEach(function (table) {
      Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th, i) {
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
    var tipEl = null;
    function hide() { if (tipEl) { tipEl.remove(); tipEl = null; } }
    document.addEventListener('mouseover', function (e) {
      var cell = e.target.closest('[data-tip]');
      if (!cell) { hide(); return; }
      hide();
      tipEl = document.createElement('div');
      tipEl.className = 'dt-tip';
      tipEl.textContent = cell.getAttribute('data-tip');
      document.body.appendChild(tipEl);
      var rect = cell.getBoundingClientRect();
      var top = rect.top - tipEl.offsetHeight - 8;
      tipEl.style.left = Math.min(rect.left, window.innerWidth - tipEl.offsetWidth - 12) + 'px';
      tipEl.style.top = (top < 0 ? rect.bottom + 8 : top) + 'px';
    });
    document.addEventListener('mouseout', function (e) {
      if (e.target.closest && e.target.closest('[data-tip]')) hide();
    });
  }

  function initCellTruncate() {
    document.querySelectorAll('table.data td.cell-long').forEach(function (td) {
      if (!td.hasAttribute('title')) td.title = td.textContent.trim();
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    initRowClick();
    initSort();
    initTooltips();
    initCellTruncate();
  });
})();
