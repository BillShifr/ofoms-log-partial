// Новый новостной UX: тосты (уведомления) из Django messages.
// Автоскрытие 5 c, ручное закрытие, типы: успех/ошибка/предупреждение/инфо.
(function () {
  function toast(text, type) {
    var box = document.querySelector('.toast-container');
    if (!box) return;
    var el = document.createElement('div');
    el.className = 'toast toast--' + type;
    el.setAttribute('role', 'status');
    var body = document.createElement('span');
    body.className = 'toast__text';
    body.textContent = text;
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'toast__close';
    close.setAttribute('aria-label', 'Закрыть');
    close.textContent = '×';
    el.appendChild(body);
    el.appendChild(close);
    box.appendChild(el);
    var hide = function () {
      el.classList.add('toast--hide');
      setTimeout(function () { el.remove(); }, 300);
    };
    close.addEventListener('click', hide);
    setTimeout(hide, 5000);
  }

  function init() {
    var alerts = document.querySelectorAll('#messages .alert');
    if (!alerts.length) return;
    alerts.forEach(function (alert) {
      var m = alert.className.match(/alert--(\w+)/);
      var tag = m ? m[1] : 'info';
      var type = tag === 'error' ? 'danger'
        : tag === 'warning' ? 'warning'
        : tag === 'info' ? 'info'
        : 'success';
      toast(alert.textContent.trim(), type);
    });
    var holder = document.getElementById('messages');
    if (holder) holder.remove();
  }

  document.addEventListener('DOMContentLoaded', init);
})();