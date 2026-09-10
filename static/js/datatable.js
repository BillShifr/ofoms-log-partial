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
    var key = function (td) {
      var v = td ? td.getAttribute('data-value') : null;
      if (v === null) v = td ? td.textContent.trim() : '';
      return td && td.getAttribute('data-type') === 'num' ? parseFloat(v) : v.toLowerCase();
    };
    var first = key(tbody.rows.length ? tbody.rows[0].cells[index] : null);
    var numeric = tbody.rows.length && tbody.rows[0].cells[index] && tbody.rows[0].cells[index].getAttribute('data-type') === 'num';
    var th = table.tHead.rows[0].cells[index];
    var head = th.getAttribute('data-sort-state') || 'none';
    var dir = head === 'asc' ? 'desc' : 'asc';
    Array.prototype.forEach.call(tbody.rows, function (row) {
      row.dataset.sortVal = key(row.cells[index]);
    });
    var rows = Array.prototype.slice.call(tbody.rows);
    rows.sort(function (a, b) {
      var av = a.dataset.sortVal, bv = b.dataset.sortVal;
      if (numeric) { av = parseFloat(a.dataset.sortVal); bv = parseFloat(b.dataset.sortVal);
        return dir === 'asc' ? av - bv : bv - av; }
      return dir === 'asc' ? String(av).localeCompare(String(bv), 'ru') : String(bv).localeCompare(String(av), 'ru');
    });
    rows.forEach(function (row) { tbody.appendChild(row); });
    Array.prototype.forEach.call(table.tHead.rows[0].cells, function (c) {
      c.classList.remove('sort-asc', 'sort-desc');
      delete c.dataset.sortState;
    });
    th.classList.add(dir === 'asc' ? 'sort-asc' : 'sort-desc');
    th.dataset.sortState = dir;
  }

  function initSort() {
    document.querySelectorAll('table.data[data-client-sort]').forEach(function (table) {
      Array.prototype.forEach.call(table.tHead.rows[0].cells, function (th, i) {
        if (isInteractive(th) || th.querySelector('a')) return;
        th.classList.add('data-sort');
        th.addEventListener('click', function () { sortTable(table, i); });
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