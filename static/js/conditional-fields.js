(function () {
  "use strict";

  function updateDependentFields(controller) {
    document
      .querySelectorAll("[data-conditional-controller]")
      .forEach(function (container) {
        if (container.dataset.conditionalController !== controller.id) return;
        var expected = (container.dataset.conditionalValues || "")
          .split(",")
          .map(function (value) { return value.trim(); });
        var visible = expected.includes("*") ? Boolean(controller.value) : expected.includes(controller.value);
        container.hidden = !visible;
        container.setAttribute("aria-hidden", String(!visible));
      });
  }

  function init() {
    var controllerIds = new Set();
    document.querySelectorAll("[data-conditional-controller]").forEach(function (container) {
      controllerIds.add(container.dataset.conditionalController);
    });
    controllerIds.forEach(function (id) {
      var controller = document.getElementById(id);
      if (!controller) return;
      updateDependentFields(controller);
      if (controller.dataset.conditionalReady !== "true") {
        controller.dataset.conditionalReady = "true";
        controller.addEventListener("change", function () { updateDependentFields(controller); });
      }
    });
  }

  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("portal:render", init);
})();
