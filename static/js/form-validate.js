// Лёгкая клиентская валидация форм (v3, 2.0.4).
// Формы с атрибутом data-validate: перехват submit, проверка нативных
// ограничений (required/pattern/min/max/тип), показ подсказки у первого
// невалидного поля и фокус на него. Серверная валидация остаётся основной.
(function () {
  function showTip(input, message) {
    var existing = input.parentNode.querySelector('.validation-tip');
    if (existing) existing.remove();
    var tip = document.createElement('span');
    tip.className = 'validation-tip';
    tip.textContent = message || input.validationMessage || 'Проверьте значение поля';
    input.parentNode.appendChild(tip);
    input.classList.add('is-invalid');
    input.focus();
  }

  function clearTip(input) {
    var existing = input.parentNode.querySelector('.validation-tip');
    if (existing) existing.remove();
    input.classList.remove('is-invalid');
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('form[data-validate]').forEach(function (form) {
      form.setAttribute('novalidate', 'novalidate');
      form.addEventListener('submit', function (e) {
        clearTips(form);
        var first = null;
        for (var i = 0; i < form.elements.length; i++) {
          var el = form.elements[i];
          if (el.disabled || el.tagName === 'FIELDSET') continue;
          var validity = el.validity;
          if (validity && !validity.valid) {
            if (!first) first = el;
            if (validity.valueMissing) showTip(el, 'Обязательное поле не заполнено');
            else if (validity.typeMismatch || validity.badInput) showTip(el, 'Указано некорректное значение');
            else if (validity.patternMismatch) showTip(el, 'Значение не соответствует требуемому формату');
            else if (validity.tooShort) showTip(el, 'Значение слишком короткое');
            else if (validity.tooLong) showTip(el, 'Значение слишком длинное');
            else if (validity.rangeUnderflow || validity.rangeOverflow) showTip(el, 'Значение вне допустимого диапазона');
            else showTip(el, el.validationMessage);
            break;
          }
        }
        if (first) {
          e.preventDefault();
          e.stopImmediatePropagation();
        }
      });
    });

    function clearTips(form) {
      form.querySelectorAll('.validation-tip').forEach(function (t) { t.remove(); });
      form.querySelectorAll('.is-invalid').forEach(function (i) { i.classList.remove('is-invalid'); });
    }
  });
})();