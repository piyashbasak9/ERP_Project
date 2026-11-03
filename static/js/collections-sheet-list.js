$(function () {
    const grid = $("#collectionGrid");
    grid.jqGrid({
        url: $("#collectionSheetPage").data("grid-url"),
        datatype: "json",
        mtype: "GET",
        postData: {format: "json"},
        colModel: [
            {name: "id", key: true, hidden: true},
            {label: "Date", name: "collection_date", width: 100},
            {label: "Center", name: "center", width: 160},
            {label: "Group", name: "group", width: 120},
            {label: "Field officer", name: "field_officer", width: 160},
            {label: "Status", name: "status", width: 100},
            {label: "Collected", name: "total_collected", width: 110, align: "right"},
            {
                label: "Open",
                name: "detail_url",
                width: 80,
                sortable: false,
                formatter: value => {
                    const target = new URL(value, window.location.origin);
                    if (target.origin !== window.location.origin) return "";
                    const link = document.createElement("a");
                    link.className = "btn btn-sm btn-outline-primary";
                    link.href = target.pathname + target.search + target.hash;
                    link.textContent = "Open";
                    return link.outerHTML;
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
        pager: "#collectionPager",
        rowNum: 50,
        rowList: [25, 50, 100],
        viewrecords: true,
        autowidth: true,
        height: "auto",
        autoencode: true,
        sortname: "collection_date",
        sortorder: "desc"
    });

    const refresh = () => grid.jqGrid("setGridParam", {
        page: 1,
        postData: {
            format: "json",
            searchString: $("#collection-search").val(),
            status: $("#collection-status").val()
        }
    }).trigger("reloadGrid");
    $("#collection-search").on("input", refresh);
    $("#collection-status").on("change", refresh);
});
