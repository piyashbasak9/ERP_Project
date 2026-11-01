$(function () {
    const config = document.getElementById("reportGridConfig");
    const columns = JSON.parse(config.dataset.columns);
    const params = new URLSearchParams(new FormData(document.getElementById("reportFilters")));
    const gridUrl = new URL(config.dataset.gridUrl, window.location.origin);
    params.forEach((value, key) => {
        if (value) gridUrl.searchParams.set(key, value);
    });
    $("#reportGrid").jqGrid({
        url: gridUrl.toString(),
        datatype: "json",
        mtype: "GET",
        colModel: columns.map(column => ({
            name: column.key,
            label: column.label,
            sortable: true
        })),
        pager: "#reportPager",
        rowNum: Number(config.dataset.defaultPageSize),
        rowList: [25, 50, 100],
        sortname: columns.length ? columns[0].key : "",
        sortorder: "asc",
        autowidth: true,
        autoencode: true,
        viewrecords: true,
        footerrow: true,
        userDataOnFooter: true,
        jsonReader: {repeatitems: false},
        loadComplete: function (data) {
            if (data.userdata) $("#reportGrid").jqGrid("footerData", "set", data.userdata);
        }
    });
});
