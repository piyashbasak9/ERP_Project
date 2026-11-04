$(function () {
    const root = document.querySelector("[data-list-page]");
    if (!root) return;

    const table = root.querySelector("[data-list-grid]");
    const $grid = $(table);
    const filterForm = root.querySelector("[data-list-filters]");
    const filterControls = Array.from(filterForm.querySelectorAll("[data-filter-control]"));
    const filterFields = Array.from(filterForm.querySelectorAll("[data-filter-field]"));
    const userKey = root.dataset.userKey;
    const pageKey = root.dataset.pageKey;
    const storageKey = `erp-list:${userKey}:${pageKey}`;
    const filterStorageKey = `${storageKey}:filters`;
    const timersEnabled = root.dataset.performanceTimers === "true";
    const columns = Array.from(table.querySelectorAll("thead th")).map((cell) => {
        const name = cell.dataset.name;
        const column = {
            name,
            label: cell.textContent.trim(),
            width: Number(cell.dataset.width) || 140,
            sortable: name !== "actions",
            align: cell.dataset.align || "left",
            resizable: true,
            title: true,
            hidden: cell.dataset.hidden === "true"
                || (window.innerWidth < 1280 && cell.dataset.hidden === "true"),
        };
        if (name === "status" || name === "is_active") {
            column.formatter = (value) => {
                const text = String(value ?? "");
                const status = text.trim().toLowerCase();
                const tone = ["active", "approved", "open", "posted"].includes(status)
                    ? "success"
                    : ["pending", "dormant", "submitted", "draft"].includes(status)
                        ? "warning"
                        : ["rejected", "closed", "inactive", "written off", "suspended"].includes(status)
                            ? "danger"
                            : "neutral";
                const escaped = text.replace(/[&<>"']/g, (character) => ({
                    "&": "&amp;",
                    "<": "&lt;",
                    ">": "&gt;",
                    '"': "&quot;",
                    "'": "&#39;",
                })[character]);
                return `<span class="erp-status-tag status-${tone}">${escaped}</span>`;
            };
        }
        if (name === "actions") {
            column.formatter = (value) => value || "";
            column.formatoptions = {escape: false};
        }
        return column;
    });

    const gridUrl = new URL(root.dataset.gridUrl, window.location.origin);
    const query = new URLSearchParams(window.location.search);
    const requestedPage = Number(query.get("page")) || 1;
    const pageSize = Number(query.get("rows")) || 20;
    const sortName = query.get("sidx") || columns[0].name;
    const sortOrder = query.get("sord") === "desc" ? "desc" : "asc";
    query.delete("page");
    query.delete("rows");
    query.delete("sidx");
    query.delete("sord");
    query.delete("_search");
    query.set("ajax", "1");
    gridUrl.search = query.toString();

    let collapsed = localStorage.getItem(filterStorageKey) === "collapsed";
    const filterToggle = root.querySelector("[data-filter-toggle]");
    const filterCount = root.querySelector("[data-filter-count]");
    const filterChips = root.querySelector("[data-active-filter-chips]");
    const selectEnhancers = new Map();

    const fieldValues = (field) => Array.from(
        field.querySelectorAll("[data-filter-control]")
    ).filter((control) => control.value.trim());

    const displayValue = (control) => {
        if (control instanceof HTMLSelectElement) {
            return control.selectedOptions[0]?.textContent.trim() || control.value;
        }
        return control.value.trim();
    };

    const updateFilterUi = () => {
        filterControls.forEach((control) => {
            const clearButton = control.parentElement.querySelector("[data-filter-clear]");
            clearButton.hidden = !control.value.trim();
        });
        const activeFields = filterFields.filter((field) => fieldValues(field).length);
        filterCount.textContent = String(activeFields.length);
        filterCount.hidden = activeFields.length === 0;
        filterChips.replaceChildren();
        activeFields.forEach((field) => {
            const label = field.dataset.filterLabel;
            const value = fieldValues(field).map((control) => {
                const text = displayValue(control);
                if (control.type !== "date" || fieldValues(field).length === 1) {
                    return text;
                }
                const rangeLabel = control.getAttribute("aria-label")
                    .replace(label, "")
                    .trim();
                return `${rangeLabel}: ${text}`;
            }).join(" – ");
            const chip = document.createElement("button");
            chip.className = "erp-filter-chip";
            chip.type = "button";
            chip.dataset.filterChip = field.dataset.filterField;
            chip.setAttribute("aria-label", `Remove ${label} filter: ${value}`);
            const text = document.createElement("span");
            text.textContent = `${label}: ${value}`;
            const icon = document.createElement("i");
            icon.className = "bi bi-x";
            icon.setAttribute("aria-hidden", "true");
            chip.append(text, icon);
            chip.addEventListener("click", () => {
                field.querySelectorAll("[data-filter-control]").forEach(clearFilterControl);
                filterForm.requestSubmit();
            });
            filterChips.append(chip);
        });
        filterChips.hidden = !collapsed || activeFields.length === 0;
    };

    filterControls.filter((control) => control instanceof HTMLSelectElement)
        .forEach((select) => {
            if (typeof window.SlimSelect !== "function") {
                throw new Error("Slim Select failed to load for list filters.");
            }
            selectEnhancers.set(select, new window.SlimSelect({
                select,
                settings: {
                    showSearch: true,
                    searchPlaceholder: "Search options",
                    searchText: "No matching options",
                    placeholderText: select.options[0]?.textContent.trim() || "All",
                    ariaLabel: select.getAttribute("aria-label") || "Filter options",
                    allowDeselect: false,
                    closeOnSelect: true,
                },
                events: {afterChange: updateFilterUi},
            }));
        });

    function clearFilterControl(control) {
        const enhancer = selectEnhancers.get(control);
        if (enhancer) {
            enhancer.setSelected("");
        } else {
            control.value = "";
        }
        control.dispatchEvent(new Event("input", {bubbles: true}));
        control.dispatchEvent(new Event("change", {bubbles: true}));
    }

    filterControls.forEach((control) => {
        control.parentElement.querySelector("[data-filter-clear]")
            .addEventListener("click", () => clearFilterControl(control));
    });
    filterForm.addEventListener("input", updateFilterUi);
    filterForm.addEventListener("change", updateFilterUi);
    filterForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const parameters = new URLSearchParams();
        for (const [name, value] of new FormData(filterForm)) {
            if (String(value).trim()) parameters.append(name, value);
        }
        const target = new URL(filterForm.action, window.location.href);
        target.search = parameters.toString();
        window.location.assign(target.toString());
    });

    const setFilterCollapsed = (value) => {
        collapsed = value;
        filterForm.hidden = collapsed;
        filterToggle.setAttribute("aria-expanded", String(!collapsed));
        localStorage.setItem(filterStorageKey, collapsed ? "collapsed" : "expanded");
        updateFilterUi();
    };
    filterToggle.addEventListener("click", () => setFilterCollapsed(!collapsed));
    setFilterCollapsed(collapsed);

    const savedColumns = JSON.parse(localStorage.getItem(storageKey) || "{}");
    const savedHiddenColumns = savedColumns.hidden || savedColumns;
    columns.forEach((column) => {
        if (Object.hasOwn(savedHiddenColumns, column.name)) {
            column.hidden = savedHiddenColumns[column.name];
        }
    });
    if (Array.isArray(savedColumns.order)) {
        const order = new Map(savedColumns.order.map((name, index) => [name, index]));
        columns.sort((left, right) =>
            (order.get(left.name) ?? Number.MAX_SAFE_INTEGER)
            - (order.get(right.name) ?? Number.MAX_SAFE_INTEGER)
        );
    }

    const gridPager = root.querySelector("[data-grid-pager]");
    const jqGridPager = root.querySelector("[data-jqgrid-pager]");
    jqGridPager.id = `jqgrid-pager-${userKey}`;
    const pageInput = gridPager.querySelector("[data-page-input]");
    const pageCount = gridPager.querySelector("[data-page-count]");
    const pageSizeSelect = gridPager.querySelector("[data-page-size]");
    pageSizeSelect.value = String([20, 50, 100, 200].includes(pageSize) ? pageSize : 20);
    const pageButtons = [
        gridPager.querySelector("[data-page-first]"),
        gridPager.querySelector("[data-page-previous]"),
        gridPager.querySelector("[data-page-next]"),
        gridPager.querySelector("[data-page-last]"),
    ];
    const updatePager = (page, total) => {
        pageInput.value = String(page);
        pageInput.max = String(Math.max(total, 1));
        pageCount.textContent = String(Math.max(total, 1));
        pageButtons[0].disabled = page <= 1;
        pageButtons[1].disabled = page <= 1;
        pageButtons[2].disabled = page >= total;
        pageButtons[3].disabled = page >= total;
    };
    let started = performance.now();

    $grid.jqGrid({
        url: gridUrl.toString(),
        datatype: "json",
        mtype: "GET",
        colModel: columns,
        pager: `#${jqGridPager.id}`,
        rowNum: [20, 50, 100, 200].includes(pageSize) ? pageSize : 20,
        rowList: [20, 50, 100, 200],
        page: requestedPage,
        rownumbers: true,
        viewrecords: true,
        autowidth: true,
        shrinkToFit: true,
        forceFit: true,
        gridview: true,
        sortable: true,
        autoencode: true,
        height: 100,
        loadonce: false,
        emptyrecords: "No matching records found.",
        sortname: sortName,
        sortorder: sortOrder,
        jsonReader: {
            root: "rows",
            page: "page",
            total: "total",
            records: "records",
            repeatitems: false,
        },
        loadBeforeSend() {
            started = performance.now();
        },
        loadComplete(data) {
            if (timersEnabled) {
                const elapsed = (performance.now() - started) / 1000;
                root.querySelector("[data-load-time]").textContent = `DLT: ${elapsed.toFixed(2)}s`;
            } else {
                root.querySelector("[data-load-time]").textContent = "";
            }
            const currentUrl = new URL(window.location.href);
            currentUrl.searchParams.set("page", String(data.page || 1));
            currentUrl.searchParams.set("rows", String($grid.jqGrid("getGridParam", "rowNum")));
            currentUrl.searchParams.set("sidx", String($grid.jqGrid("getGridParam", "sortname") || ""));
            currentUrl.searchParams.set("sord", String($grid.jqGrid("getGridParam", "sortorder") || "asc"));
            window.history.replaceState({}, "", currentUrl);
            updatePager(Number(data.page) || 1, Number(data.total) || 1);
            const first = data.records ? ((data.page - 1) * Number($grid.jqGrid("getGridParam", "rowNum"))) + 1 : 0;
            const last = data.records ? Math.min(first + Number($grid.jqGrid("getGridParam", "rowNum")) - 1, data.records) : 0;
            root.querySelector("[data-view-range]").textContent = `View ${first} - ${last} of ${data.records}`;
            const hidden = {};
            const order = [];
            $grid.jqGrid("getGridParam", "colModel").forEach((column) => {
                if (column.name !== "rn" && column.name !== "cb") {
                    hidden[column.name] = Boolean(column.hidden);
                    order.push(column.name);
                }
            });
            localStorage.setItem(storageKey, JSON.stringify({hidden, order}));
        },
    });

    function goToPage(page) {
        const total = Number($grid.jqGrid("getGridParam", "lastpage")) || 1;
        const target = Math.min(total, Math.max(1, Number(page) || 1));
        $grid.jqGrid("setGridParam", {page: target}).trigger("reloadGrid");
    }

    pageButtons.forEach((button, index) => {
        button.addEventListener("click", () => {
            const page = Number($grid.jqGrid("getGridParam", "page")) || 1;
            const total = Number($grid.jqGrid("getGridParam", "lastpage")) || 1;
            goToPage([1, page - 1, page + 1, total][index]);
        });
    });
    pageInput.addEventListener("change", () => goToPage(pageInput.value));
    pageInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            goToPage(pageInput.value);
        }
    });
    pageSizeSelect.addEventListener("change", () => {
        $grid.jqGrid("setGridParam", {rowNum: Number(pageSizeSelect.value), page: 1})
            .trigger("reloadGrid");
    });
    gridPager.querySelector("[data-grid-refresh]").addEventListener("click", () => {
        $grid.trigger("reloadGrid");
    });
    gridPager.querySelector("[data-column-chooser]").addEventListener("click", () => {
        $grid.jqGrid("columnChooser", {
            done(perm) {
                if (perm) this.jqGrid("remapColumns", perm, true);
            },
        });
    });

    function resizeGrid() {
        const wrapper = root.querySelector(".ui-jqgrid");
        const header = root.querySelector(".ui-jqgrid-hdiv");
        const area = root.querySelector(".erp-list-grid-wrap").getBoundingClientRect();
        if (!wrapper || !header || area.width < 1) return;
        $grid.jqGrid("setGridWidth", area.width, true);
        const height = Math.max(100, wrapper.getBoundingClientRect().height - header.getBoundingClientRect().height - 1);
        $grid.jqGrid("setGridHeight", height);
    }

    $(window).on("resize", resizeGrid);
    new ResizeObserver(resizeGrid).observe(root.querySelector(".erp-list-grid-wrap"));
    window.setTimeout(resizeGrid, 0);
});
