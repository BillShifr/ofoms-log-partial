(function () {
  "use strict";

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!(form instanceof HTMLFormElement)) return;

    var submitter = event.submitter;
    var confirmation =
      (submitter && submitter.getAttribute("data-confirm")) ||
      form.getAttribute("data-confirm");
    if (confirmation && !window.confirm(confirmation)) {
      event.preventDefault();
      return;
    }

    if (event.defaultPrevented || !submitter || submitter.disabled) return;
    submitter.disabled = true;
    submitter.setAttribute("aria-busy", "true");
    submitter.dataset.originalLabel = submitter.textContent;
    submitter.textContent = submitter.getAttribute("data-submitting-label") || "Отправка…";
  });

  window.addEventListener("pageshow", function () {
    document.querySelectorAll('[aria-busy="true"][data-original-label]').forEach(function (button) {
      button.disabled = false;
      button.removeAttribute("aria-busy");
      button.textContent = button.dataset.originalLabel;
      delete button.dataset.originalLabel;
    });
  });

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest("[data-ui-action]");
    if (!trigger) return;
    var action = trigger.getAttribute("data-ui-action");
    if (action === "back") history.back();
    if (action === "reload") location.reload();
    if (action === "print") window.print();
  });
})();
