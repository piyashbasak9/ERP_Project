$(function () {
    const config = document.getElementById("reportGridConfig");
    const filterForm = document.getElementById("reportFilters");
    const filterToggle = document.querySelector("[data-report-filter-toggle]");
    const filterChips = document.querySelector("[data-report-filter-chips]");
    const reportEmptyState = document.querySelector("[data-report-empty-state]");
    const filterPreferenceKey = `erp-report-filters:${filterForm.dataset.userKey}:${window.location.pathname}`;
    let savedFilterPreference = localStorage.getItem(filterPreferenceKey);
    const mobileFilters = window.matchMedia("(max-width: 575.98px)");
    const filterCollapsed = mobileFilters.matches && savedFilterPreference !== "expanded";
    filterForm.hidden = filterCollapsed;
    filterToggle.setAttribute("aria-expanded", String(!filterCollapsed));
    const setFiltersCollapsed = (collapsed, persist = false) => {
        filterForm.hidden = collapsed;
        filterToggle.setAttribute("aria-expanded", String(!collapsed));
        updateReportFilterChips();
        if (persist) {
            savedFilterPreference = collapsed ? "collapsed" : "expanded";
            localStorage.setItem(filterPreferenceKey, savedFilterPreference);
        }
    };
    filterToggle.addEventListener("click", () => {
        setFiltersCollapsed(!filterForm.hidden, true);
    });
    mobileFilters.addEventListener("change", (event) => {
        setFiltersCollapsed(event.matches && savedFilterPreference !== "expanded");
    });

    function updateReportFilterChips() {
        filterChips.replaceChildren();
        const activeFilters = Array.from(filterForm.elements).filter((control) =>
            control.name && control.value.trim() && !["submit", "button"].includes(control.type)
        );
        activeFilters.forEach((control) => {
            const label = filterForm.querySelector(`label[for="${CSS.escape(control.id)}"]`);
            const value = control instanceof HTMLSelectElement
                ? control.selectedOptions[0]?.textContent.trim() || control.value
                : control.value.trim();
            const chip = document.createElement("button");
            chip.className = "erp-filter-chip";
            chip.type = "button";
            chip.setAttribute("aria-label", `Remove ${label?.textContent.trim() || control.name} filter`);
            const text = document.createElement("span");
            text.textContent = `${label?.textContent.trim() || control.name}: ${value}`;
            const icon = document.createElement("i");
            icon.className = "bi bi-x";
            icon.setAttribute("aria-hidden", "true");
            chip.append(text, icon);
            chip.addEventListener("click", () => {
                control.value = "";
                filterForm.requestSubmit();
            });
            filterChips.append(chip);
        });
        filterChips.hidden = !filterForm.hidden || activeFilters.length === 0;
    }

    filterForm.addEventListener("input", updateReportFilterChips);
    filterForm.addEventListener("change", updateReportFilterChips);
    updateReportFilterChips();

    const columns = JSON.parse(config.dataset.columns);
    const params = new URLSearchParams(new FormData(filterForm));
    const gridUrl = new URL(config.dataset.gridUrl, window.location.origin);
    params.forEach((value, key) => {
        if (value) gridUrl.searchParams.set(key, value);
    });
    const $grid = $("#reportGrid");
    const reportCards = document.querySelector("[data-report-cards]");
    const reportPageSummary = document.querySelector("[data-report-page-summary]");
    const reportPrevious = document.querySelector("[data-report-previous]");
    const reportNext = document.querySelector("[data-report-next]");
    const reportPageSize = document.querySelector("[data-report-page-size]");
    reportPageSize.value = "20";

    function renderReportCards() {
        reportCards.replaceChildren();
        const rows = Array.from(document.querySelectorAll("#reportGrid tr.jqgrow"));
        if (!rows.length) {
            return;
        }

        rows.forEach((row) => {
            const cellFor = (column) => Array.from(row.cells).find(cell =>
                (cell.getAttribute("aria-describedby") || "").endsWith(`_${column.key}`)
            );
            const card = document.createElement("article");
            card.className = "erp-list-card";
            const heading = document.createElement("h2");
            heading.className = "erp-list-card-title";
            heading.textContent = (columns[0] && cellFor(columns[0])?.textContent.trim()) || "Record";
            card.append(heading);

            if (columns.length > 1) {
                const details = document.createElement("details");
                details.className = "erp-list-card-more";
                const toggle = document.createElement("summary");
                toggle.textContent = "More";
                const fields = document.createElement("dl");
                fields.className = "erp-list-card-details";
                columns.slice(1).forEach((column) => {
                    const term = document.createElement("dt");
                    term.textContent = column.label;
                    const description = document.createElement("dd");
                    description.textContent = cellFor(column)?.textContent.trim() || "—";
                    fields.append(term, description);
                });
                details.append(toggle, fields);
                card.append(details);
            }
            reportCards.append(card);
        });
    }

    function updateMobilePager(data) {
        const page = Number(data.page) || 1;
        const total = Number(data.total) || 1;
        reportPageSummary.textContent = `Page ${page} of ${total}`;
        reportPrevious.disabled = page <= 1;
        reportNext.disabled = page >= total;
    }

    reportPrevious.addEventListener("click", () => {
        const page = Number($grid.jqGrid("getGridParam", "page")) || 1;
        $grid.jqGrid("setGridParam", {page: Math.max(1, page - 1)}).trigger("reloadGrid");
    });
    reportNext.addEventListener("click", () => {
        const page = Number($grid.jqGrid("getGridParam", "page")) || 1;
        const total = Number($grid.jqGrid("getGridParam", "lastpage")) || 1;
        $grid.jqGrid("setGridParam", {page: Math.min(total, page + 1)}).trigger("reloadGrid");
    });
    reportPageSize.addEventListener("change", () => {
        $grid.jqGrid("setGridParam", {
            rowNum: Number(reportPageSize.value),
            page: 1,
        }).trigger("reloadGrid");
    });

    $grid.jqGrid({
        url: gridUrl.toString(),
        datatype: "json",
        mtype: "GET",
        colModel: columns.map(column => ({
            name: column.key,
            label: column.label,
            sortable: true
        })),
        pager: "#reportPager",
        rowNum: window.innerWidth < 576 ? 20 : Number(config.dataset.defaultPageSize),
        rowList: [20, 25, 50, 100],
        sortname: columns.length ? columns[0].key : "",
        sortorder: "asc",
        autowidth: true,
        autoencode: true,
        viewrecords: true,
        footerrow: true,
        userDataOnFooter: true,
        jsonReader: {repeatitems: false},
        loadComplete: function (data) {
            if (data.userdata) $grid.jqGrid("footerData", "set", data.userdata);
            reportEmptyState.hidden = Number(data.records) > 0;
            renderReportCards();
            updateMobilePager(data);
        }
    });

    function resizeGrid() {
        const container = document.querySelector(".report-page .table-responsive");
        const width = container?.clientWidth || 0;
        if (width > 0) $grid.jqGrid("setGridWidth", width, true);
    }

    let resizeTimer;
    $(window).off("resize.erpReportGrid").on("resize.erpReportGrid", function () {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(resizeGrid, 100);
    });
    window.setTimeout(resizeGrid, 0);
});
