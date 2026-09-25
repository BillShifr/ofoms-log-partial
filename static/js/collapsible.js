(function () {
  function stateKey(el) {
    return 'collapsible:' + (el.id || el.getAttribute('data-key') || location.pathname + ':' + (el.querySelector('summary') || {}).textContent);
  }

  function init() {
    document.querySelectorAll('details.collapsible').forEach(function (el) {
      if (el.dataset.collapsibleReady === 'true') return;
      el.dataset.collapsibleReady = 'true';
      var key = stateKey(el);
      if (el.dataset.forceOpen === 'true') {
        el.open = true;
        return;
      }
      var saved = null;
      try { saved = localStorage.getItem(key); } catch (e) { /* noop */ }
      if (saved === 'closed') el.open = false;
      else if (saved === 'open') el.open = true;
      el.addEventListener('toggle', function () {
        try { localStorage.setItem(key, el.open ? 'open' : 'closed'); }
        catch (e) { /* noop */ }
      });
    });
  }

  document.addEventListener('DOMContentLoaded', init);
  document.addEventListener('portal:render', init);
})();
