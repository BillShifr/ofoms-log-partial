(function () {
  "use strict";
  var pageController = null;

  function initExchangeUpload() {
    var form = document.getElementById("upload-form");
    if (!form) return;
    var fileInput = form.querySelector('[type="file"]');
    if (!fileInput) return;
    form.addEventListener("submit", function (event) {
      if (!fileInput.files.length) return;
      var file = fileInput.files[0];
      var name = (file.name || "").toLowerCase();
      var validName =
        ((name.startsWith("users") || name.startsWith("g1")) && name.endsWith(".xml")) ||
        name.endsWith(".xlsx");
      var maxSize = Number(form.dataset.maxFileSize || 0);
      if (validName && (!maxSize || file.size <= maxSize)) return;
      event.preventDefault();
      fileInput.classList.add("is-invalid");
      fileInput.setCustomValidity(form.dataset.fileError || "Проверьте тип и размер файла");
      fileInput.reportValidity();
    });
    fileInput.addEventListener("change", function () {
      fileInput.setCustomValidity("");
      fileInput.classList.remove("is-invalid");
    });
  }

  function initDocumentTitle() {
    var fileInput = document.getElementById("id_file");
    var titleInput = document.getElementById("id_title");
    if (!fileInput || !titleInput) return;
    fileInput.addEventListener("change", function () {
      if (!titleInput.value && fileInput.files.length) {
        titleInput.value = (fileInput.files[0].name || "")
          .replace(/\.[^.]+$/, "")
          .slice(0, 200);
      }
    });
  }

  function initParticipants(signal) {
    var search = document.getElementById("participant-search");
    var list = document.querySelector(".participant-pick");
    var tokens = document.querySelector(".participant-tokens");
    var panel = document.getElementById("participant-options");
    if (!search || !list || !search.dataset.suggestUrl) return;
    var boxes = Array.prototype.slice.call(list.querySelectorAll('input[type="checkbox"]'));
    var activeIndex = -1;

    function selectedIds() {
      return boxes.filter(function (box) { return box.checked; }).map(function (box) { return String(box.value); });
    }

    function renderTokens() {
      if (!tokens) return;
      tokens.innerHTML = "";
      boxes.filter(function (box) { return box.checked; }).forEach(function (box) {
        var chip = document.createElement("span");
        chip.className = "participant-token";
        chip.textContent = (box.closest("label") || box).textContent.trim();
        var remove = document.createElement("button");
        remove.type = "button";
        remove.setAttribute("aria-label", "Удалить участника " + chip.textContent);
        remove.textContent = "×";
        remove.addEventListener("click", function () {
          box.checked = false;
          renderTokens();
          search.focus();
        });
        chip.appendChild(remove);
        tokens.appendChild(chip);
      });
    }

    function closePanel() {
      if (panel) {
        panel.innerHTML = "";
        panel.hidden = true;
      }
      search.setAttribute("aria-expanded", "false");
      activeIndex = -1;
    }

    function setActive(items, index) {
      activeIndex = index;
      items.forEach(function (item, i) {
        item.classList.toggle("is-active", i === activeIndex);
        item.setAttribute("aria-selected", String(i === activeIndex));
      });
    }

    function choose(item) {
      var box = boxes.find(function (candidate) {
        return String(candidate.value) === String(item.id);
      });
      if (!box) return;
      box.checked = true;
      search.value = "";
      closePanel();
      renderTokens();
      search.focus();
    }

    function show(items) {
      if (!panel) return;
      closePanel();
      var picked = selectedIds();
      items = items.filter(function (item) {
        return item && item.id && picked.indexOf(String(item.id)) === -1;
      });
      if (!items.length) return;
      panel.hidden = false;
      search.setAttribute("aria-expanded", "true");
      items.forEach(function (item, index) {
        var button = document.createElement("button");
        button.type = "button";
        button.className = "autocomplete__item";
        button.id = "participant-option-" + item.id;
        button.setAttribute("role", "option");
        button.textContent = item.label;
        button.addEventListener("click", function () { choose(item); });
        panel.appendChild(button);
        if (index === 0) setActive(Array.prototype.slice.call(panel.children), 0);
      });
    }

    search.addEventListener("input", function () {
      var query = search.value.trim();
      if (query.length < 3) {
        closePanel();
        return;
      }
      fetch(search.dataset.suggestUrl + "?q=" + encodeURIComponent(query))
        .then(function (response) { return response.json(); })
        .then(function (data) { show(data.suggestions || []); })
        .catch(closePanel);
    });
    search.addEventListener("keydown", function (event) {
      if (!panel || panel.hidden) return;
      var items = Array.prototype.slice.call(panel.children);
      if (event.key === "Escape") {
        closePanel();
      } else if (event.key === "ArrowDown") {
        event.preventDefault();
        setActive(items, Math.min(items.length - 1, activeIndex + 1));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive(items, Math.max(0, activeIndex - 1));
      } else if (event.key === "Enter" && activeIndex >= 0) {
        event.preventDefault();
        items[activeIndex].click();
      }
    });
    document.addEventListener("click", function (event) {
      if (panel && !panel.contains(event.target) && event.target !== search) closePanel();
    }, { signal: signal });
    renderTokens();
  }

  function initTaskTabs() {
    var tabs = Array.prototype.slice.call(document.querySelectorAll('.tab[data-tab]'));
    function activate(tab, focus) {
      var target = tab.dataset.tab;
      tabs.forEach(function (item) {
        var active = item === tab;
        item.classList.toggle('is-active', active);
        item.setAttribute('aria-selected', String(active));
        item.tabIndex = active ? 0 : -1;
      });
      document.querySelectorAll('.tab-panel[data-panel]').forEach(function (panel) {
        var active = panel.dataset.panel === target;
        panel.classList.toggle('is-active', active);
        panel.hidden = !active;
      });
      if (focus) tab.focus();
    }
    tabs.forEach(function (tab, index) {
      if (tab.dataset.tabReady === 'true') return;
      tab.dataset.tabReady = 'true';
      tab.addEventListener("click", function () {
        activate(tab, false);
      });
      tab.addEventListener('keydown', function (event) {
        var next = index;
        if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
        else if (event.key === 'ArrowLeft') next = (index - 1 + tabs.length) % tabs.length;
        else if (event.key === 'Home') next = 0;
        else if (event.key === 'End') next = tabs.length - 1;
        else return;
        event.preventDefault();
        activate(tabs[next], true);
      });
    });
  }

  function initAssigneeSearch(signal) {
    var search = document.querySelector("[data-assignee-search]");
    var selectBox = document.getElementById("assignee-select");
    var panel = document.getElementById("assignee-options");
    if (!search || !selectBox || !panel || !search.dataset.suggestUrl) return;
    var select = selectBox.querySelector("select");
    if (!select) return;
    var activeIndex = -1;
    var requestNumber = 0;
    var selectedLabel = "";
    var disclosure = search.closest(".collapsible");

    function syncFromSelect() {
      var option = select.options[select.selectedIndex];
      selectedLabel = option && option.value ? option.textContent.trim() : "";
      search.value = selectedLabel;
      search.setCustomValidity("");
    }

    function closePanel() {
      panel.innerHTML = "";
      panel.hidden = true;
      if (disclosure) disclosure.classList.remove("has-open-popover");
      search.setAttribute("aria-expanded", "false");
      search.removeAttribute("aria-activedescendant");
      activeIndex = -1;
    }

    function setActive(items, index) {
      activeIndex = index;
      items.forEach(function (item, itemIndex) {
        var active = itemIndex === index;
        item.classList.toggle("is-active", active);
        item.setAttribute("aria-selected", String(active));
      });
      if (items[index]) search.setAttribute("aria-activedescendant", items[index].id);
    }

    function choose(item) {
      select.value = String(item.id);
      selectedLabel = item.label;
      search.value = item.label;
      search.setCustomValidity("");
      closePanel();
      search.focus();
    }

    function show(items) {
      closePanel();
      items = items.filter(function (item) { return item && item.id; });
      if (!items.length) return;
      panel.hidden = false;
      if (disclosure) disclosure.classList.add("has-open-popover");
      search.setAttribute("aria-expanded", "true");
      items.forEach(function (item) {
        var button = document.createElement("button");
        button.type = "button";
        button.id = "assignee-option-" + item.id;
        button.className = "autocomplete__item";
        button.setAttribute("role", "option");
        button.textContent = item.label;
        button.addEventListener("click", function () { choose(item); });
        panel.appendChild(button);
      });
      setActive(Array.prototype.slice.call(panel.children), 0);
    }

    function load(query) {
      var currentRequest = ++requestNumber;
      fetch(search.dataset.suggestUrl + "?q=" + encodeURIComponent(query))
        .then(function (response) { return response.json(); })
        .then(function (data) {
          if (currentRequest === requestNumber) show(data.suggestions || []);
        })
        .catch(function () {
          if (currentRequest === requestNumber) closePanel();
        });
    }

    search.addEventListener("focus", function () {
      load(search.value === selectedLabel ? "" : search.value.trim());
    });
    search.addEventListener("input", function () {
      var query = search.value.trim();
      if (search.value !== selectedLabel) select.value = "";
      search.setCustomValidity(query && !select.value ? "Выберите сотрудника из списка" : "");
      if (!query) load("");
      else if (query.length >= 3) load(query);
      else closePanel();
    });
    search.addEventListener("keydown", function (event) {
      if (panel.hidden) return;
      var items = Array.prototype.slice.call(panel.children);
      if (event.key === "Escape") closePanel();
      else if (event.key === "ArrowDown") {
        event.preventDefault();
        setActive(items, Math.min(items.length - 1, activeIndex + 1));
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        setActive(items, Math.max(0, activeIndex - 1));
      } else if (event.key === "Enter" && items[activeIndex]) {
        event.preventDefault();
        items[activeIndex].click();
      }
    });
    document.addEventListener("click", function (event) {
      if (!panel.contains(event.target) && !event.target.closest("#assignee-wrap")) {
        closePanel();
      }
    }, { signal: signal });
    select.addEventListener("change", syncFromSelect);
    syncFromSelect();
  }

  function initConditionalFields() {
    document.querySelectorAll("[data-conditional-controller][data-conditional-values]").forEach(function (field) {
      var controller = document.getElementById(field.dataset.conditionalController);
      if (!controller) return;
      var values = field.dataset.conditionalValues.split(",").map(function (value) {
        return value.trim();
      });
      function sync() {
        field.hidden = values.indexOf(controller.value) === -1;
      }
      controller.addEventListener("change", sync);
      sync();
    });
  }

  function initReactions() {
    document.querySelectorAll(".reactions .reaction[form]").forEach(function (button) {
      button.addEventListener("click", function (event) {
        var form = document.getElementById(button.getAttribute("form"));
        if (!form) return;
        event.preventDefault();
        var previousPressed = button.getAttribute("aria-pressed") === "true";
        var countNode = button.querySelector(".reaction__count");
        var previousCount = Number(countNode ? countNode.textContent : 0) || 0;
        var nextPressed = !previousPressed;
        button.setAttribute("aria-pressed", String(nextPressed));
        button.classList.toggle("reaction--active", nextPressed);
        if (countNode) countNode.textContent = String(Math.max(0, previousCount + (nextPressed ? 1 : -1)));
        button.disabled = true;

        var body = new FormData(form);
        body.set("emoji", button.value);
        fetch(form.action, {
          method: "POST",
          body: body,
          headers: { "X-Requested-With": "XMLHttpRequest" },
          credentials: "same-origin"
        }).then(function (response) {
          if (!response.ok) throw new Error("reaction failed");
          return response.json();
        }).then(function (data) {
          if (!data.ok) throw new Error(data.error || "reaction failed");
          button.closest(".reactions").querySelectorAll(".reaction").forEach(function (item) {
            var emoji = item.value;
            var active = Boolean(data.pressed && data.pressed[emoji]);
            item.setAttribute("aria-pressed", String(active));
            item.classList.toggle("reaction--active", active);
            var node = item.querySelector(".reaction__count");
            if (node && data.counts) node.textContent = String(data.counts[emoji] || 0);
          });
        }).catch(function () {
          button.setAttribute("aria-pressed", String(previousPressed));
          button.classList.toggle("reaction--active", previousPressed);
          if (countNode) countNode.textContent = String(previousCount);
          if (window.showToast) window.showToast("Не удалось обновить реакцию. Попробуйте ещё раз.", "danger");
        }).finally(function () {
          button.disabled = false;
        });
      });
    });
  }

  function restoreSubmitButton(form) {
    var button = form.querySelector('[aria-busy="true"][data-original-label]');
    if (!button) return;
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = button.dataset.originalLabel;
    delete button.dataset.originalLabel;
  }

  function initGlobalActions() {
    document.addEventListener("click", function (event) {
      var toggle = event.target.closest("[data-control-group-toggle]");
      if (!toggle) return;
      var group = toggle.closest("tbody[data-control-group]");
      if (!group) return;
      var expanded = toggle.getAttribute("aria-expanded") === "true";
      group.querySelectorAll("tr[data-control-row]").forEach(function (row) {
        row.hidden = expanded;
      });
      toggle.setAttribute("aria-expanded", String(!expanded));
      var label = toggle.querySelector(".control-group__action");
      if (label) label.textContent = expanded ? "Развернуть" : "Свернуть";
    });

    document.addEventListener("submit", function (event) {
      var form = event.target.closest("[data-theme-create-form]");
      if (!form) return;
      event.preventDefault();
      var errorBox = form.querySelector("[data-theme-form-errors]");
      if (errorBox) {
        errorBox.hidden = true;
        errorBox.textContent = "";
      }
      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
        headers: { "Accept": "application/json", "X-Requested-With": "XMLHttpRequest" }
      }).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok || !data.ok) throw data;
          return data;
        });
      }).then(function (data) {
        document.querySelectorAll('select[name="theme"]').forEach(function (select) {
          var option = document.createElement("option");
          option.value = String(data.id);
          option.textContent = data.label;
          option.selected = select.closest("form[data-validate]") !== null;
          select.appendChild(option);
        });
        form.reset();
        var dialog = form.closest("dialog");
        if (dialog && typeof dialog.close === "function") dialog.close();
        if (window.showToast) window.showToast("Тема создана и доступна в списке.", "success");
      }).catch(function (data) {
        var messages = [];
        Object.keys((data && data.errors) || {}).forEach(function (field) {
          data.errors[field].forEach(function (error) {
            messages.push(error.message || String(error));
          });
        });
        if (errorBox) {
          errorBox.textContent = messages.join(" ") || "Не удалось создать тему.";
          errorBox.hidden = false;
        }
      }).finally(function () {
        restoreSubmitButton(form);
      });
    });

    document.addEventListener("submit", function (event) {
      var form = event.target.closest("[data-task-action-create-form]");
      if (!form) return;
      event.preventDefault();
      var errorBox = form.querySelector("[data-task-action-form-errors]");
      if (errorBox) {
        errorBox.hidden = true;
        errorBox.textContent = "";
      }
      fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        credentials: "same-origin",
        headers: { "Accept": "application/json", "X-Requested-With": "XMLHttpRequest" }
      }).then(function (response) {
        return response.json().then(function (data) {
          if (!response.ok || !data.ok) throw data;
          return data;
        });
      }).then(function (data) {
        document.querySelectorAll('select[name="command"]').forEach(function (select) {
          var option = document.createElement("option");
          option.value = String(data.id);
          option.textContent = data.label;
          option.selected = true;
          select.appendChild(option);
          select.dispatchEvent(new Event("change", { bubbles: true }));
        });
        form.reset();
        var dialog = form.closest("dialog");
        if (dialog && typeof dialog.close === "function") dialog.close();
        if (window.showToast) window.showToast("Действие создано и выбрано в задаче.", "success");
      }).catch(function (data) {
        var messages = [];
        Object.keys((data && data.errors) || {}).forEach(function (field) {
          data.errors[field].forEach(function (error) {
            messages.push(error.message || String(error));
          });
        });
        if (errorBox) {
          errorBox.textContent = messages.join(" ") || "Не удалось создать действие.";
          errorBox.hidden = false;
        }
      }).finally(function () {
        restoreSubmitButton(form);
      });
    });
  }

  function initPage() {
    if (pageController) pageController.abort();
    pageController = new AbortController();
    initExchangeUpload();
    initDocumentTitle();
    initParticipants(pageController.signal);
    initTaskTabs();
    initAssigneeSearch(pageController.signal);
    initConditionalFields();
    initReactions();
  }

  document.addEventListener("DOMContentLoaded", function () {
    initGlobalActions();
    initPage();
  });
  document.addEventListener("portal:render", initPage);
})();
