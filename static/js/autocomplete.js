// Автозаполнение текстовых полей (v3, 2.0.6).
// input[data-autocomplete] — GET на URL из data-autocomplete-url (по умолчанию
// /journal/suggest/), параметры field=<data-autocomplete>&q=<ввод>.
// Debounce 300 мс, минимальная длина — 3 символа. Список — выпадающая панель.
(function () {
  var MIN_LEN = 3;
  var DEBOUNCE = 300;
  var timer = null;
  var panel = null;

  function removePanel() {
    if (panel) { panel.remove(); panel = null; }
  }

  function showPanel(input, items) {
    removePanel();
    if (!items.length) return;
    panel = document.createElement('div');
    panel.className = 'autocomplete autocomplete--anchored';
    panel.setAttribute('role', 'listbox');
    items.forEach(function (v) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'autocomplete__item';
      item.setAttribute('role', 'option');
      item.textContent = v;
      item.addEventListener('click', function () {
        input.value = v;
        removePanel();
      });
      panel.appendChild(item);
    });
    var host = input.parentElement;
    if (!host) return;
    host.classList.add('autocomplete-host');
    host.appendChild(panel);
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('input[data-autocomplete]').forEach(function (input) {
      input.setAttribute('autocomplete', 'off');
      input.addEventListener('input', function () {
        var q = input.value.trim();
        if (timer) clearTimeout(timer);
        if (q.length < MIN_LEN) { removePanel(); return; }
        timer = setTimeout(function () {
          var url = input.getAttribute('data-autocomplete-url') || '/journal/suggest/';
          var field = input.getAttribute('data-autocomplete');
          fetch(url + '?field=' + encodeURIComponent(field) + '&q=' + encodeURIComponent(q))
            .then(function (r) { return r.json(); })
            .then(function (data) { showPanel(input, data.suggestions || []); })
            .catch(function () { removePanel(); });
        }, DEBOUNCE);
      });
    });
    document.addEventListener('click', function (e) {
      if (panel && !panel.contains(e.target) && !(e.target.closest && e.target.closest('[data-autocomplete]'))) {
        removePanel();
      }
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') removePanel();
    });
  });
})();
