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
    if (!search || !list || !search.dataset.suggestUrl) return;
    var boxes = Array.prototype.slice.call(list.querySelectorAll("input"));
    search.addEventListener("input", function () {
      var query = search.value.trim();
      if (query.length < 3) return;
      fetch(search.dataset.suggestUrl + "?q=" + encodeURIComponent(query))
        .then(function (response) { return response.json(); })
        .then(function (data) {
          (data.suggestions || []).forEach(function (item) {
            var box = boxes.find(function (candidate) {
              return String(candidate.value) === String(item.id);
            });
            if (box && !box.checked) {
              box.checked = true;
              search.value = "";
            }
          });
        })
        .catch(function () {});
    });
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

  document.addEventListener("DOMContentLoaded", function () {
    initReportFilter();
    initExchangeUpload();
    initDocumentTitle();
    initParticipants();
    initTaskTabs();
    initAssigneeSearch();
  });
})();
