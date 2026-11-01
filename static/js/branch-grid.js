$(function () {
    const wrapper = $("#pageWrapper");
    const gridUrl = wrapper.data("grid-url");

    function fitPageWrapperHeight() {
        const top = wrapper.offset().top;
        const footerHeight = $("footer.footer-custom").outerHeight() || 0;
        const bottomPadding = parseFloat($("main.main-content").css("padding-bottom")) || 0;
        const available = $(window).height() - top - footerHeight - bottomPadding - 1;
        wrapper.css("height", available + "px");
    }

    function resizeGridBody() {
        const tableResponsive = $(".table-responsive");
        const header = $(".ui-jqgrid-hdiv");
        const pager = $(".ui-jqgrid-pager");
        const available = tableResponsive.height() - (header.outerHeight() || 0) - (pager.outerHeight() || 0);
        $("#branchGrid").jqGrid("setGridHeight", available > 0 ? available : 200);
    }

    $("#branchGrid").jqGrid({
        url: gridUrl,
        datatype: "json",
        mtype: "GET",
        colModel: [
            {label: "ID", name: "id", width: 60, align: "center", sortable: true},
            {label: "Name", name: "name", width: 220, sortable: true},
            {label: "Code", name: "code", width: 120, sortable: true},
            {label: "Created By", name: "created_by", width: 120, sortable: true},
            {label: "Updated By", name: "updated_by", width: 120, sortable: true},
            {label: "Created At", name: "created_at", width: 160, sortable: true},
            {label: "Updated At", name: "updated_at", width: 160, sortable: true},
            {
                label: "Actions",
                name: "actions",
                width: 120,
                align: "center",
                sortable: false,
                formatter: cellvalue => cellvalue || "",
                formatoptions: {escape: false}
            }
        ],
        rowNum: 20,
        rowList: [20, 50, 100, 200, 500],
        pager: "#branchPager",
        viewrecords: true,
        autowidth: true,
        autoencode: true,
        shrinkToFit: true,
        forceFit: true,
        gridview: true,
        height: "100%",
        loadonce: false,
        jsonReader: {
            root: "rows",
            page: "page",
            total: "total",
            records: "records",
            repeatitems: false
        }
    });

    function resizePage() {
        $("#branchGrid").jqGrid("setGridWidth", $(".table-responsive").width());
        fitPageWrapperHeight();
        resizeGridBody();
    }

    $(window).on("resize", resizePage);
    fitPageWrapperHeight();
    resizeGridBody();
    window.setTimeout(fitPageWrapperHeight, 300);

    $("#btnSearch").on("click", function () {
        const params = new URLSearchParams({
            ajax: "1",
            name: $("#search_name").val(),
            code: $("#search_code").val()
        });
        $("#branchGrid").jqGrid("setGridParam", {
            url: `${gridUrl.split("?")[0]}?${params}`,
            page: 1
        }).trigger("reloadGrid");
    });
});
