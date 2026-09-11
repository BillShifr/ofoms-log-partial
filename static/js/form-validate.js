// Лёгкая клиентская валидация форм (v3, 2.0.4).
// Формы с атрибутом data-validate: перехват submit, проверка нативных
// ограничений (required/pattern/min/max/тип), показ подсказки у первого
// невалидного поля и фокус на него. Серверная валидация остаётся основной.
(function () {
  var generatedId = 0;

  function ensureId(element, prefix) {
    if (!element.id) {
      generatedId += 1;
      element.id = prefix + '-' + generatedId;
    }
    return element.id;
  }

  function describedBy(input) {
    return (input.getAttribute('aria-describedby') || '').split(/\s+/).filter(Boolean);
  }

  function addDescription(input, element) {
    var ids = describedBy(input);
    var id = ensureId(element, input.id + '-description');
    if (ids.indexOf(id) === -1) ids.push(id);
    input.setAttribute('aria-describedby', ids.join(' '));
  }

  function removeDescription(input, element) {
    if (!element.id) return;
    var ids = describedBy(input).filter(function (id) { return id !== element.id; });
    if (ids.length) input.setAttribute('aria-describedby', ids.join(' '));
    else input.removeAttribute('aria-describedby');
  }

  function enhanceField(field) {
    var input = field.querySelector('input:not([type="hidden"]), select, textarea');
    if (!input) return;
    ensureId(input, 'field');

    var label = field.querySelector('label:not(.checkbox)');
    if (label && !label.getAttribute('for')) label.setAttribute('for', input.id);

    field.querySelectorAll('.field-error, .errorlist, .alert--error, .helptext').forEach(function (item) {
      addDescription(input, item);
      if (item.matches('.field-error, .errorlist, .alert--error')) {
        input.setAttribute('aria-invalid', 'true');
      }
    });
  }

  function showTip(input, message) {
    var existing = input.parentNode.querySelector('.validation-tip');
    if (existing) existing.remove();
    var tip = document.createElement('span');
    tip.className = 'validation-tip';
    tip.setAttribute('role', 'alert');
    tip.textContent = message || input.validationMessage || 'Проверьте значение поля';
    input.parentNode.appendChild(tip);
    addDescription(input, tip);
    input.classList.add('is-invalid');
    input.setAttribute('aria-invalid', 'true');
    input.focus();
  }

  function clearTip(input) {
    var existing = input.parentNode.querySelector('.validation-tip');
    if (existing) {
      removeDescription(input, existing);
      existing.remove();
    }
    input.classList.remove('is-invalid');
    if (!input.parentNode.querySelector('.field-error, .errorlist, .alert--error')) {
      input.removeAttribute('aria-invalid');
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.field').forEach(enhanceField);
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
      form.querySelectorAll('.validation-tip').forEach(function (tip) {
        var input = tip.parentNode.querySelector('input:not([type="hidden"]), select, textarea');
        if (input) removeDescription(input, tip);
        tip.remove();
      });
      form.querySelectorAll('.is-invalid').forEach(function (input) {
        input.classList.remove('is-invalid');
        if (!input.parentNode.querySelector('.field-error, .errorlist, .alert--error')) {
          input.removeAttribute('aria-invalid');
        }
      });
    }
  });
})();
