// Лёгкая клиентская валидация форм (v3, 2.0.4).
// Все формы с пользовательскими полями: перехват submit, проверка нативных
// ограничений и декларативных групповых правил. Серверная валидация остаётся основной.
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

  function isEditable(element) {
    if (!element || element.disabled || element.matches('[data-validation-ignore]')) return false;
    if (!element.matches('input, select, textarea')) return false;
    return !['hidden', 'submit', 'button', 'reset', 'image'].includes(element.type);
  }

  function isVisible(element) {
    return element.type !== 'hidden' && !element.hidden && !element.closest('[hidden]');
  }

  function hasValue(element) {
    if (element.type === 'checkbox' || element.type === 'radio') return element.checked;
    if (element.type === 'file') return Boolean(element.files && element.files.length);
    return String(element.value || '').trim() !== '';
  }

  function editableElements(form) {
    return Array.prototype.filter.call(form.elements, isEditable);
  }

  function validationTarget(form, controls) {
    var selector = form.dataset.validationTarget;
    if (selector) {
      try {
        var explicit = form.querySelector(selector);
        if (explicit) return explicit;
      } catch (error) {}
    }
    return controls.find(isVisible) || controls[0] || null;
  }

  function validateGroupRules(form, controls) {
    var candidates = controls;
    var selector = form.dataset.requireSelector;
    if (selector) {
      try { candidates = Array.prototype.slice.call(form.querySelectorAll(selector)); }
      catch (error) { candidates = []; }
    } else if (!form.hasAttribute('data-require-input')) {
      return true;
    }
    if (candidates.some(hasValue)) return true;
    var target = validationTarget(form, controls);
    if (target) {
      showTip(target, form.dataset.requireMessage || 'Заполните хотя бы одно поле');
    }
    return false;
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.field').forEach(enhanceField);
    document.querySelectorAll('form').forEach(function (form) {
      if ((form.getAttribute('method') || '').toLowerCase() === 'dialog') return;
      if (!form.querySelector('button[type="submit"], input[type="submit"]')) return;
      var controls = editableElements(form);
      if (!controls.length) return;
      form.setAttribute('novalidate', 'novalidate');
      form.addEventListener('submit', function (e) {
        clearTips(form);
        var first = null;
        for (var i = 0; i < controls.length; i++) {
          var el = controls[i];
          if (!isVisible(el)) continue;
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
        if (first || !validateGroupRules(form, controls)) {
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
