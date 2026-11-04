$(function () {
    $(".js-jqgrid-source").each(function (tableIndex) {
        const source = this;
        const $source = $(source);
        const container = source.closest(".container-fluid, .container") || source.parentElement;
        const headers = Array.from(source.querySelectorAll("thead th")).map((header, index) => {
            const label = header.textContent.trim();
            return label || (index === source.querySelectorAll("thead th").length - 1 ? "Actions" : `Column ${index + 1}`);
        });
        if (!headers.length) return;

        const rows = Array.from(source.querySelectorAll("tbody tr"))
            .filter(row => !row.querySelector("td[colspan]"))
            .map((row, rowIndex) => {
                const cells = Array.from(row.cells);
                const record = {id: String(rowIndex + 1)};
                headers.forEach((_header, index) => {
                    const cell = cells[index];
                    record[`column_${index}`] = cell ? cell.textContent.trim() : "";
                    record[`html_${index}`] = cell ? cell.innerHTML : "";
                });
                return record;
            });
        const emptyMessage = source.querySelector("tbody td[colspan]")?.textContent.trim()
            || "No records found.";
        const $responsive = $source.closest(".table-responsive");
        const hasServerPagination = container.querySelector(".pagination") !== null;
        const gridId = `listGrid${tableIndex}`;
        const pagerId = `${gridId}Pager`;
        const searchId = `${gridId}Search`;

        source.id = gridId;
        $responsive.addClass("jqgrid-responsive");
        const toolbar = document.createElement("div");
        toolbar.className = "list-grid-toolbar";
        const searchLabel = document.createElement("label");
        searchLabel.htmlFor = searchId;
        searchLabel.setAttribute("aria-label", "Search records");
        const searchIcon = document.createElement("i");
        searchIcon.className = "bi bi-search";
        searchIcon.setAttribute("aria-hidden", "true");
        searchLabel.append(searchIcon);
        const searchInput = document.createElement("input");
        searchInput.id = searchId;
        searchInput.className = "form-control form-control-sm";
        searchInput.type = "search";
        searchInput.placeholder = "Search loaded records";
        const recordCount = document.createElement("span");
        recordCount.className = "list-grid-count";
        recordCount.textContent = `${rows.length} records`;
        toolbar.append(searchLabel, searchInput, recordCount);
        $responsive.before(toolbar);

        const pager = document.createElement("div");
        pager.id = pagerId;
        pager.className = "list-grid-pager";
        if (!hasServerPagination) $responsive.after(pager);

        const columns = headers.map((label, index) => {
            const isActionColumn = label.toLowerCase() === "actions"
                || (!label && index === headers.length - 1);
            const column = {
                label,
                name: `column_${index}`,
                index: `column_${index}`,
                width: index === headers.length - 1 ? 135 : 120,
                sortable: true,
            };
            if (isActionColumn) {
                column.formatter = (_value, _options, row) => row[`html_${index}`] || "";
                column.formatoptions = {escape: false};
            }
            return column;
        });

        $source.jqGrid({
            datatype: "local",
            data: rows,
            colModel: columns,
            pager: hasServerPagination ? null : `#${pagerId}`,
            rowNum: hasServerPagination ? Math.max(rows.length, 1) : 50,
            rowList: [25, 50, 100, 200],
            viewrecords: true,
            emptyrecords: emptyMessage,
            height: "auto",
            autowidth: true,
            shrinkToFit: true,
            forceFit: true,
            gridview: true,
            autoencode: true,
            loadonce: true,
            sortname: "column_0",
            sortorder: "asc",
            jsonReader: {id: "id"}
        });

        $(`#${searchId}`).on("input", function () {
            const query = this.value.trim();
            const filters = {
                groupOp: "OR",
                rules: headers.map((_header, index) => ({
                    field: `column_${index}`,
                    op: "cn",
                    data: query
                }))
            };
            $source.jqGrid("setGridParam", {
                search: Boolean(query),
                postData: {filters: query ? JSON.stringify(filters) : ""}
            }).trigger("reloadGrid");
        });

        $source.on("jqGridAfterLoadComplete jqGridGridComplete", function () {
            const count = $source.jqGrid("getGridParam", "records") || 0;
            toolbar.querySelector(".list-grid-count").textContent = `${count} records`;
        });

        function resizeGrid() {
            const width = $responsive.width();
            if (width > 0) $source.jqGrid("setGridWidth", width, true);
            const gridTop = $source.closest(".ui-jqgrid").offset()?.top || 0;
            const footerHeight = $("footer.footer-custom").outerHeight() || 0;
            const bodyHeight = Math.max(220, window.innerHeight - gridTop - footerHeight - 80);
            $source.jqGrid("setGridHeight", bodyHeight);
        }

        $(window).on("resize", resizeGrid);
        resizeGrid();
    });
});
