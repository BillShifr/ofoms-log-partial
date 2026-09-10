// Общий Collapsible (v3, 2.0.5): сохраняет состояние свёрнут/развёрнут.
// Применяется ко всем details.collapsible; при свёрнутом состоянии кнопка
// «Применить» (вне details) остаётся видимой.
(function () {
  function stateKey(el) {
    return 'collapsible:' + (el.id || el.getAttribute('data-key') || location.pathname + ':' + (el.querySelector('summary') || {}).textContent);
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('details.collapsible').forEach(function (el) {
      var key = stateKey(el);
      var saved = null;
      try { saved = localStorage.getItem(key); } catch (e) { /* noop */ }
      if (saved === 'closed') el.open = false;
      else if (saved === 'open') el.open = true;
      el.addEventListener('toggle', function () {
        try { localStorage.setItem(key, el.open ? 'open' : 'closed'); }
        catch (e) { /* noop */ }
      });
    });
  });
})();