$(function () {
    const config = document.getElementById("loanProductGridConfig");
    const grid = $("#loanProductGrid");
    const editUrl = config.dataset.editUrl.replace("/0/", "/");
    const activateUrl = config.dataset.activateUrl.replace("/0/activate/", "/");
    const deactivateUrl = config.dataset.deactivateUrl.replace("/0/deactivate/", "/");
    const csrf = () => {
        const part = document.cookie.split("; ").find(item => item.startsWith("csrftoken="));
        return part ? decodeURIComponent(part.slice("csrftoken=".length)) : "";
    };
    grid.jqGrid({
        url: config.dataset.productsUrl,
        datatype: "json",
        mtype: "GET",
        postData: {format: "json"},
        colModel: [
            {name: "id", key: true, hidden: true},
            {label: "Code", name: "code", width: 90},
            {label: "Name", name: "name", width: 170},
            {label: "Method", name: "method", width: 110},
            {label: "Rate %", name: "rate", width: 85, align: "right"},
            {label: "Amount range", name: "amount", width: 145},
            {label: "Term range", name: "term", width: 90},
            {label: "Frequency", name: "frequency", width: 100},
            {label: "Status", name: "active", width: 75, formatter: value => value ? "Active" : "Inactive"},
            {
                label: "Actions",
                name: "actions",
                sortable: false,
                width: 220,
                formatter: (_value, _options, row) => {
                    const id = Number(row.id);
                    const edit = document.createElement("a");
                    edit.className = "btn btn-sm btn-outline-primary me-1";
                    edit.href = editUrl + id + "/?popup=1";
                    edit.dataset.popup = "";
                    edit.dataset.popupTitle = "Edit loan product";
                    edit.textContent = "Edit";
                    const toggle = document.createElement("button");
                    toggle.className = "btn btn-sm " + (row.active ? "btn-outline-danger" : "btn-outline-success");
                    toggle.type = "button";
                    toggle.dataset.toggleProduct = row.active
                        ? deactivateUrl + id + "/deactivate/"
                        : activateUrl + id + "/activate/";
                    toggle.textContent = row.active ? "Deactivate" : "Activate";
                    const wrapper = document.createElement("span");
                    wrapper.append(edit, toggle);
                    return wrapper.outerHTML;
                }
            }
        ],
        jsonReader: {
            root: "rows",
            page: "page",
            total: "total",
            records: "records",
            repeatitems: false,
            id: "id"
        },
        pager: "#loanProductPager",
        rowNum: 50,
        rowList: [25, 50, 100],
        viewrecords: true,
        autowidth: true,
        height: "auto",
        autoencode: true,
        sortname: "code",
        sortorder: "asc"
    });
    const refresh = () => grid.jqGrid("setGridParam", {
        page: 1,
        postData: {
            format: "json",
            searchString: $("#loan-product-search").val(),
            status: $("#loan-product-status").val()
        }
    }).trigger("reloadGrid");
    $("#loan-product-search").on("input", refresh);
    $("#loan-product-status").on("change", refresh);
    grid.on("click", "[data-toggle-product]", async function () {
        const response = await fetch(this.dataset.toggleProduct, {
            method: "POST",
            headers: {"X-CSRFToken": csrf(), "Accept": "application/json"}
        });
        const body = await response.json();
        if (window.handleAuthChallenge(body)) return;
        if (!response.ok) {
            window.notify.error(body.message || "Product status could not be changed.");
            return;
        }
        window.notify.success(body.message);
        grid.trigger("reloadGrid");
    });
});
