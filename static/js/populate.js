window.addEventListener("load", function () {
  (function ($) {
    "use strict";
    $(document).on("ready", function () {
      $("#id_z_f").on("change keyup", function () {
        $("#id_in_f").val(this.value);
      });
      $("#id_z_i").on("change keyup", function () {
        $("#id_in_i").val(this.value);
      });
      $("#id_z_o").on("change keyup", function () {
        $("#id_in_o").val(this.value);
      });
    });
  })(django.jQuery);
});