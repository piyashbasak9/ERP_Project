$(function () {
    const resizeHandlers = [];
    $(window).off("resize.erpListGrid");

    $(".js-jqgrid-source").each(function (tableIndex) {
        const source = this;
        const $source = $(source);
        const container = source.closest(".container-fluid, .container") || source.parentElement;
        const headers = Array.from(source.querySelectorAll("thead th")).map((header, index) => {
            const label = header.textContent.trim();
            return label || (index === source.querySelectorAll("thead th").length - 1 ? "Actions" : `Column ${index + 1}`);
        });
        if (!headers.length) return;

        const actionCells = new Map();
        const rows = Array.from(source.querySelectorAll("tbody tr"))
            .filter(row => !row.querySelector("td[colspan]"))
            .map((row, rowIndex) => {
                const cells = Array.from(row.cells);
                const id = String(rowIndex + 1);
                const record = {id};
                headers.forEach((_header, index) => {
                    const cell = cells[index];
                    record[`column_${index}`] = cell ? cell.textContent.trim() : "";
                    record[`html_${index}`] = cell ? cell.innerHTML : "";
                    if (
                        cell
                        && (headers[index].toLowerCase() === "actions"
                            || (!headers[index] && index === headers.length - 1))
                    ) {
                        actionCells.set(id, cell.cloneNode(true));
                    }
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
        const pagerWrap = document.createElement("div");
        pagerWrap.className = "list-grid-pager-wrap";
        pagerWrap.append(pager);
        if (!hasServerPagination) $responsive.after(pagerWrap);

        const cardList = document.createElement("div");
        cardList.className = "erp-list-cards legacy-list-cards";
        cardList.dataset.listCards = "";
        cardList.setAttribute("aria-label", "Records");
        $responsive.after(cardList);

        const mobilePager = document.createElement("nav");
        mobilePager.className = "erp-grid-pager legacy-list-mobile-pager";
        mobilePager.setAttribute("aria-label", "Grid pagination");
        const previousButton = document.createElement("button");
        previousButton.className = "erp-grid-page-button";
        previousButton.type = "button";
        previousButton.textContent = "Previous";
        previousButton.setAttribute("aria-label", "Previous page");
        const pageSummary = document.createElement("span");
        pageSummary.className = "erp-grid-page-summary";
        const nextButton = document.createElement("button");
        nextButton.className = "erp-grid-page-button";
        nextButton.type = "button";
        nextButton.textContent = "Next";
        nextButton.setAttribute("aria-label", "Next page");
        const pageSize = document.createElement("select");
        pageSize.setAttribute("aria-label", "Rows per page");
        [20, 50, 100].forEach(size => {
            const option = document.createElement("option");
            option.value = String(size);
            option.textContent = String(size);
            pageSize.append(option);
        });
        mobilePager.append(previousButton, pageSummary, nextButton, pageSize);
        if (!hasServerPagination) pagerWrap.after(mobilePager);

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
            sortorder: source.dataset.defaultSortOrder === "desc" ? "desc" : "asc",
            jsonReader: {id: "id"}
        });

        let currentCardPage = 1;
        const renderCards = () => {
            const query = searchInput.value.trim().toLocaleLowerCase();
            const matchingRows = rows.filter(row => headers.some((_header, index) =>
                String(row[`column_${index}`] || "").toLocaleLowerCase().includes(query)
            ));
            const perPage = Number(pageSize.value) || 20;
            const pageCount = Math.max(1, Math.ceil(matchingRows.length / perPage));
            currentCardPage = Math.min(currentCardPage, pageCount);
            const pageRows = matchingRows.slice(
                (currentCardPage - 1) * perPage,
                currentCardPage * perPage,
            );
            cardList.replaceChildren();
            if (!pageRows.length) {
                const empty = document.createElement("p");
                empty.className = "erp-list-card-empty";
                empty.textContent = emptyMessage;
                cardList.append(empty);
            }
            pageRows.forEach(row => {
                const card = document.createElement("article");
                card.className = "erp-list-card";
                const title = document.createElement("h2");
                title.className = "erp-list-card-title";
                title.textContent = row.column_0 || emptyMessage;
                card.append(title);

                const summary = document.createElement("dl");
                summary.className = "erp-list-card-summary";
                if (headers[1]) {
                    const label = document.createElement("dt");
                    label.textContent = headers[1];
                    const value = document.createElement("dd");
                    value.textContent = row.column_1 || "—";
                    summary.append(label, value);
                }
                card.append(summary);

                const detailIndexes = headers
                    .map((_header, index) => index)
                    .filter(index => index > 1 && headers[index].toLowerCase() !== "actions");
                if (detailIndexes.length) {
                    const details = document.createElement("details");
                    details.className = "erp-list-card-more";
                    const more = document.createElement("summary");
                    more.textContent = "More";
                    const list = document.createElement("dl");
                    list.className = "erp-list-card-details";
                    detailIndexes.forEach(index => {
                        const label = document.createElement("dt");
                        label.textContent = headers[index];
                        const value = document.createElement("dd");
                        value.textContent = row[`column_${index}`] || "—";
                        list.append(label, value);
                    });
                    details.append(more, list);
                    card.append(details);
                }

                const actionCell = actionCells.get(row.id);
                if (actionCell?.childNodes.length) {
                    const actions = document.createElement("details");
                    actions.className = "erp-list-card-actions";
                    const summary = document.createElement("summary");
                    summary.textContent = "Actions";
                    const content = document.createElement("div");
                    content.className = "erp-list-card-action-items";
                    Array.from(actionCell.childNodes, node => node.cloneNode(true))
                        .forEach(node => content.append(node));
                    actions.append(summary, content);
                    card.append(actions);
                }
                cardList.append(card);
            });
            pageSummary.textContent = `Page ${currentCardPage} of ${pageCount}`;
            previousButton.disabled = currentCardPage <= 1;
            nextButton.disabled = currentCardPage >= pageCount;
            mobilePager.hidden = hasServerPagination;
        };
        pageSize.value = "20";
        previousButton.addEventListener("click", () => {
            currentCardPage = Math.max(1, currentCardPage - 1);
            renderCards();
        });
        nextButton.addEventListener("click", () => {
            currentCardPage += 1;
            renderCards();
        });
        pageSize.addEventListener("change", () => {
            currentCardPage = 1;
            renderCards();
        });
        renderCards();

        $(`#${searchId}`).on("input", function () {
            const query = this.value.trim();
            currentCardPage = 1;
            renderCards();
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

        resizeHandlers.push(resizeGrid);
        resizeGrid();
    });

    if (resizeHandlers.length) {
        $(window).on("resize.erpListGrid", function () {
            resizeHandlers.forEach(resizeGrid => resizeGrid());
        });
    }
});
