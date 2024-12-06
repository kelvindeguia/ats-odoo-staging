odoo.define('crm.crm_refresh', function (require) {
    "use strict";

    var core = require('web.core');
    var session = require('web.session');

    function applyStrikethrough() {
        var field = document.getElementById("email_from");
        if (field) {
            field.style.textDecoration = "line-through";
        }
    }

    $(document).ready(function () {
        $('#my_button').click(function () {
            applyStrikethrough();
        });
    });
});
