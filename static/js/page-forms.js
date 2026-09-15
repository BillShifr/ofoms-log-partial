(function () {
  "use strict";

  function initReportFilter() {
    var form = document.getElementById("report-filter-form");
    if (!form) return;
    form.addEventListener("submit", function (event) {
      var from = form.querySelector('[name="date_from"]');
      var to = form.querySelector('[name="date_to"]');
      if (!from || !to || from.value || to.value) return;
      event.preventDefault();
      from.setCustomValidity("Укажите хотя бы дату начала или окончания периода");
      from.reportValidity();
      [from, to].forEach(function (element) {
        element.classList.add("is-invalid");
        element.addEventListener("input", function clearDateError() {
          from.setCustomValidity("");
          from.classList.remove("is-invalid");
          to.classList.remove("is-invalid");
          element.removeEventListener("input", clearDateError);
        });
      });
    });
  }

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

  function initParticipants() {
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
    });
    renderTokens();
  }

  function initTaskTabs() {
    document.querySelectorAll(".tab[data-tab]").forEach(function (tab) {
      tab.addEventListener("click", function () {
        var target = tab.dataset.tab;
        document.querySelectorAll(".tab[data-tab]").forEach(function (item) {
          var active = item === tab;
          item.classList.toggle("is-active", active);
          item.setAttribute("aria-selected", String(active));
        });
        document.querySelectorAll(".tab-panel[data-panel]").forEach(function (panel) {
          panel.classList.toggle("is-active", panel.dataset.panel === target);
        });
      });
    });
  }

  function initAssigneeSearch() {
    var search = document.querySelector("[data-assignee-search]");
    var selectBox = document.getElementById("assignee-select");
    if (!search || !selectBox || !search.dataset.suggestUrl) return;
    var select = selectBox.querySelector("select");
    var panel = null;
    selectBox.hidden = true;

    function removePanel() {
      if (panel) panel.remove();
      panel = null;
    }

    search.addEventListener("input", function () {
      var query = search.value.trim();
      if (query.length < 3) {
        removePanel();
        return;
      }
      fetch(search.dataset.suggestUrl + "?q=" + encodeURIComponent(query))
        .then(function (response) { return response.json(); })
        .then(function (data) {
          removePanel();
          var items = (data.suggestions || []).filter(function (item) {
            return item && item.id;
          });
          if (!items.length) return;
          panel = document.createElement("div");
          panel.className = "autocomplete autocomplete--anchored";
          items.forEach(function (item) {
            var button = document.createElement("button");
            button.type = "button";
            button.className = "autocomplete__item";
            button.textContent = item.label;
            button.addEventListener("click", function () {
              select.value = item.id;
              search.value = item.label;
              removePanel();
            });
            panel.appendChild(button);
          });
          search.parentNode.appendChild(panel);
        })
        .catch(removePanel);
    });
    document.addEventListener("click", function (event) {
      if (panel && !panel.contains(event.target) && !event.target.closest("#assignee-wrap")) {
        removePanel();
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") removePanel();
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

  document.addEventListener("DOMContentLoaded", function () {
    initReportFilter();
    initExchangeUpload();
    initDocumentTitle();
    initParticipants();
    initTaskTabs();
    initAssigneeSearch();
    initReactions();
  });
})();
