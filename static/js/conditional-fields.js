(function () {
  "use strict";

  function updateDependentFields(controller) {
    document
      .querySelectorAll('[data-conditional-controller="' + controller.id + '"]')
      .forEach(function (container) {
        var expected = (container.dataset.conditionalValues || "")
          .split(",")
          .map(function (value) { return value.trim(); });
        var visible = expected.includes("*") ? Boolean(controller.value) : expected.includes(controller.value);
        container.hidden = !visible;
        container.setAttribute("aria-hidden", String(!visible));
      });
  }

  document.addEventListener("DOMContentLoaded", function () {
    var controllerIds = new Set();
    document.querySelectorAll("[data-conditional-controller]").forEach(function (container) {
      controllerIds.add(container.dataset.conditionalController);
    });
    controllerIds.forEach(function (id) {
      var controller = document.getElementById(id);
      if (!controller) return;
      updateDependentFields(controller);
      controller.addEventListener("change", function () { updateDependentFields(controller); });
    });
  });
})();
