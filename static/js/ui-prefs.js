// Персональные настройки интерфейса (v3, 2.12): тема и размер шрифта.
// Храним в localStorage, применяем к <html data-theme / data-font>.
(function () {
  var THEME_KEY = 'ui:theme';
  var FONT_KEY = 'ui:font';

  function load() {
    var theme = null, font = null;
    try {
      theme = localStorage.getItem(THEME_KEY);
      font = localStorage.getItem(FONT_KEY);
    } catch (e) { /* noop */ }
    if (theme === 'dark' || theme === 'light') {
      document.documentElement.setAttribute('data-theme', theme);
    }
    if (font === 'md' || font === 'lg') {
      document.documentElement.setAttribute('data-font', font);
    }
  }

  function setTheme(value) {
    document.documentElement.setAttribute('data-theme', value);
    try { localStorage.setItem(THEME_KEY, value); } catch (e) { /* noop */ }
    syncButtons();
  }

  function setFont(value) {
    document.documentElement.setAttribute('data-font', value);
    try { localStorage.setItem(FONT_KEY, value); } catch (e) { /* noop */ }
    syncButtons();
  }

  function syncButtons() {
    var theme = document.documentElement.getAttribute('data-theme');
    var font = document.documentElement.getAttribute('data-font') || 'base';
    document.querySelectorAll('[data-ui-theme]').forEach(function (b) {
      var active = b.getAttribute('data-ui-theme') === theme;
      b.classList.toggle('btn--active', active);
      b.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    document.querySelectorAll('[data-ui-font]').forEach(function (b) {
      b.classList.toggle('btn--active', b.getAttribute('data-ui-font') === font);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    load();
    document.querySelectorAll('[data-ui-theme]').forEach(function (b) {
      b.addEventListener('click', function () { setTheme(b.getAttribute('data-ui-theme')); });
    });
    document.querySelectorAll('[data-ui-font]').forEach(function (b) {
      b.addEventListener('click', function () { setFont(b.getAttribute('data-ui-font')); });
    });
    syncButtons();
  });
})();
