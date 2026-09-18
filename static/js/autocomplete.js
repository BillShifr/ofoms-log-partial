// Доступное автозаполнение текстовых полей (v3, 2.0.6).
(function () {
  var MIN_LEN = 3;
  var DEBOUNCE = 300;
  var instanceNumber = 0;

  function initInput(input) {
    if (input.dataset.autocompleteReady === 'true') return;
    input.dataset.autocompleteReady = 'true';
    instanceNumber += 1;

    var timer = null;
    var panel = null;
    var activeIndex = -1;
    var requestNumber = 0;
    var listboxId = 'autocomplete-listbox-' + instanceNumber;

    input.setAttribute('autocomplete', 'off');
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-controls', listboxId);

    function items() {
      return panel ? Array.prototype.slice.call(panel.querySelectorAll('[role="option"]')) : [];
    }

    function setActive(index) {
      var options = items();
      activeIndex = options.length ? Math.max(0, Math.min(index, options.length - 1)) : -1;
      options.forEach(function (option, optionIndex) {
        var active = optionIndex === activeIndex;
        option.classList.toggle('is-active', active);
        option.setAttribute('aria-selected', String(active));
      });
      if (activeIndex >= 0) {
        input.setAttribute('aria-activedescendant', options[activeIndex].id);
        options[activeIndex].scrollIntoView({ block: 'nearest' });
      } else {
        input.removeAttribute('aria-activedescendant');
      }
    }

    function closePanel() {
      if (panel) panel.remove();
      panel = null;
      activeIndex = -1;
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
    }

    function choose(value) {
      input.value = value;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      closePanel();
    }

    function showPanel(values) {
      closePanel();
      if (!values.length) return;
      panel = document.createElement('div');
      panel.id = listboxId;
      panel.className = 'autocomplete autocomplete--anchored';
      panel.setAttribute('role', 'listbox');
      values.forEach(function (value, index) {
        var label = typeof value === 'string' ? value : value.label;
        var option = document.createElement('button');
        option.type = 'button';
        option.id = listboxId + '-option-' + index;
        option.className = 'autocomplete__item';
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', 'false');
        option.tabIndex = -1;
        option.textContent = label;
        option.addEventListener('pointerdown', function (event) {
          event.preventDefault();
          choose(label);
        });
        panel.appendChild(option);
      });
      var host = input.parentElement;
      if (!host) return;
      host.classList.add('autocomplete-host');
      host.appendChild(panel);
      input.setAttribute('aria-expanded', 'true');
    }

    input.addEventListener('input', function () {
      var query = input.value.trim();
      if (timer) clearTimeout(timer);
      requestNumber += 1;
      var currentRequest = requestNumber;
      if (query.length < MIN_LEN) {
        closePanel();
        return;
      }
      timer = setTimeout(function () {
        var url = input.getAttribute('data-autocomplete-url') || '/journal/suggest/';
        var field = input.getAttribute('data-autocomplete');
        fetch(url + '?field=' + encodeURIComponent(field) + '&q=' + encodeURIComponent(query))
          .then(function (response) {
            if (!response.ok) throw new Error('suggestions unavailable');
            return response.json();
          })
          .then(function (data) {
            if (currentRequest === requestNumber && input.value.trim() === query) {
              showPanel(data.suggestions || []);
            }
          })
          .catch(function () {
            if (currentRequest === requestNumber) closePanel();
          });
      }, DEBOUNCE);
    });

    input.addEventListener('keydown', function (event) {
      var options = items();
      if (event.key === 'Escape') {
        closePanel();
      } else if (event.key === 'ArrowDown' && options.length) {
        event.preventDefault();
        setActive(activeIndex + 1);
      } else if (event.key === 'ArrowUp' && options.length) {
        event.preventDefault();
        setActive(activeIndex < 0 ? options.length - 1 : activeIndex - 1);
      } else if (event.key === 'Enter' && activeIndex >= 0) {
        event.preventDefault();
        choose(options[activeIndex].textContent);
      }
    });

    input.addEventListener('blur', function () {
      window.setTimeout(closePanel, 120);
    });
  }

  function initInputs() {
    document.querySelectorAll('input[data-autocomplete]').forEach(initInput);
  }

  document.addEventListener('DOMContentLoaded', initInputs);
  document.addEventListener('portal:render', initInputs);
})();
