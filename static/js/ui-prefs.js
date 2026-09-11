// Персональные настройки интерфейса (v3, 2.12): тема, контраст и размер шрифта.
// Храним в localStorage, применяем к <html data-theme / data-font / data-contrast>.
(function () {
  var THEME_KEY = 'ui:theme';
  var FONT_KEY = 'ui:font';
  var CONTRAST_KEY = 'ui:contrast';
  var THEMES = ['light', 'dark'];
  var FONTS = ['base', 'a', 'a-plus', 'a-plus-plus'];
  var CONTRASTS = ['default', 'white', 'black'];

  function read(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
  }

  function write(key, value) {
    try { localStorage.setItem(key, value); } catch (e) { /* noop */ }
  }

  function allowed(values, value, fallback) {
    return values.indexOf(value) !== -1 ? value : fallback;
  }

  function load() {
    var preferredTheme = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    var storedFont = read(FONT_KEY);
    if (storedFont === 'md') storedFont = 'base';
    if (storedFont === 'lg') storedFont = 'a';
    document.documentElement.setAttribute('data-theme', allowed(THEMES, read(THEME_KEY), preferredTheme));
    document.documentElement.setAttribute('data-font', allowed(FONTS, storedFont, 'base'));
    document.documentElement.setAttribute('data-contrast', allowed(CONTRASTS, read(CONTRAST_KEY), 'default'));
  }

  function setTheme(value) {
    document.documentElement.setAttribute('data-theme', value);
    write(THEME_KEY, value);
    syncButtons();
  }

  function setFont(value) {
    document.documentElement.setAttribute('data-font', value);
    write(FONT_KEY, value);
    syncButtons();
  }

  function setContrast(value) {
    document.documentElement.setAttribute('data-contrast', value);
    write(CONTRAST_KEY, value);
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
      var active = b.getAttribute('data-ui-font') === font;
      b.classList.toggle('btn--active', active);
      b.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
    var contrast = document.documentElement.getAttribute('data-contrast') || 'default';
    document.querySelectorAll('[data-ui-contrast]').forEach(function (b) {
      var active = b.getAttribute('data-ui-contrast') === contrast;
      b.classList.toggle('btn--active', active);
      b.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  load();

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('[data-ui-theme]').forEach(function (b) {
      b.addEventListener('click', function () { setTheme(b.getAttribute('data-ui-theme')); });
    });
    document.querySelectorAll('[data-ui-font]').forEach(function (b) {
      b.addEventListener('click', function () { setFont(b.getAttribute('data-ui-font')); });
    });
    document.querySelectorAll('[data-ui-contrast]').forEach(function (b) {
      b.addEventListener('click', function () { setContrast(b.getAttribute('data-ui-contrast')); });
    });
    syncButtons();
  });
})();
