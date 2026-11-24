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
    const columns = Array.from(table.querySelectorAll("thead th")).map((cell, index) => {
        const name = cell.dataset.name;
        const priority = Math.min(3, Number(cell.dataset.priority) || index + 1);
        const column = {
            name,
            label: cell.textContent.trim(),
            priority,
            defaultHidden: cell.dataset.hidden === "true",
            userHidden: cell.dataset.hidden === "true",
            width: Number(cell.dataset.width) || 140,
            sortable: name !== "actions" && cell.dataset.sortable !== "false",
            align: cell.dataset.align || "left",
            resizable: true,
            title: true,
            hidden: cell.dataset.hidden === "true"
                || (window.innerWidth < 1024 && priority > 2),
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
    const sortName = query.get("sidx") || root.dataset.defaultSortName || columns[0].name;
    const sortOrder = query.get("sord")
        ? (query.get("sord") === "desc" ? "desc" : "asc")
        : (root.dataset.defaultSortOrder === "desc" ? "desc" : "asc");
    query.delete("page");
    query.delete("rows");
    query.delete("sidx");
    query.delete("sord");
    query.delete("_search");
    query.set("ajax", "1");
    gridUrl.search = query.toString();

    const savedFilterPreference = localStorage.getItem(filterStorageKey);
    let collapsed = savedFilterPreference === "collapsed"
        || (!savedFilterPreference && window.innerWidth < 576);
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
                    contentLocation: document.body,
                    contentPosition: "fixed",
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
        if (window.Turbo) window.Turbo.visit(target.toString());
        else window.location.assign(target.toString());
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
            column.userHidden = Boolean(savedHiddenColumns[column.name]);
        }
        column.hidden = column.userHidden
            || (window.innerWidth < 1024 && column.priority > (window.innerWidth < 576 ? 1 : 2));
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
    const pageSummary = gridPager.querySelector("[data-page-summary]");
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
        pageSummary.textContent = `Page ${page} of ${Math.max(total, 1)}`;
        pageButtons[0].disabled = page <= 1;
        pageButtons[1].disabled = page <= 1;
        pageButtons[2].disabled = page >= total;
        pageButtons[3].disabled = page >= total;
    };
    let started = performance.now();
    const cardList = root.querySelector("[data-list-cards]");
    const listState = root.querySelector("[data-list-state]");
    const addLink = root.querySelector(".erp-page-tools a.erp-icon-button[data-popup]");
    let hasLoaded = false;

    function showListState(state, message) {
        listState.replaceChildren();
        listState.hidden = false;
        listState.dataset.state = state;
        listState.setAttribute("role", state === "error" ? "alert" : "status");
        const text = document.createElement("p");
        text.textContent = message;
        listState.append(text);
        if (state === "empty" && addLink) {
            const addButton = document.createElement("a");
            addButton.className = "btn btn-sm btn-primary";
            addButton.href = addLink.href;
            addButton.dataset.popup = "";
            addButton.dataset.popupTitle = addLink.dataset.popupTitle || "";
            addButton.textContent = addLink.dataset.popupTitle || "Add record";
            listState.append(addButton);
        }
        const gridWrapper = root.querySelector(".ui-jqgrid");
        const hideGrid = state === "empty" || state === "error"
            || (state === "loading" && !hasLoaded);
        if (gridWrapper) gridWrapper.hidden = hideGrid;
        cardList.hidden = hideGrid;
    }

    function clearListState() {
        listState.hidden = true;
        listState.removeAttribute("data-state");
        listState.setAttribute("role", "status");
        const gridWrapper = root.querySelector(".ui-jqgrid");
        if (gridWrapper) gridWrapper.hidden = false;
        cardList.hidden = false;
    }

    function renderMobileCards() {
        if (!cardList) return;
        const rows = Array.from(root.querySelectorAll(".ui-jqgrid-btable tr.jqgrow"));
        cardList.replaceChildren();
        if (!rows.length) return;

        const keyColumn = columns.find(column =>
            column.priority === 1 && column.name !== "actions"
                && !column.defaultHidden && !column.userHidden
        );
        rows.forEach(row => {
            const cellFor = (column) => Array.from(row.cells).find(cell =>
                (cell.getAttribute("aria-describedby") || "").endsWith(`_${column.name}`)
            );
            const card = document.createElement("article");
            card.className = "erp-list-card";
            const heading = document.createElement("h2");
            heading.className = "erp-list-card-title";
            heading.textContent = (keyColumn && cellFor(keyColumn)?.textContent.trim()) || "Record";
            card.append(heading);

            const keyFields = columns.filter(column =>
                column.priority === 1 && column.name !== "actions"
                    && !column.defaultHidden && !column.userHidden && column !== keyColumn
            );
            const summary = document.createElement("dl");
            summary.className = "erp-list-card-summary";
            keyFields.forEach(column => appendCardField(summary, column, cellFor(column)));
            card.append(summary);

            const detailFields = columns.filter(column =>
                column.priority > 1 && column.name !== "actions"
                    && !column.defaultHidden && !column.userHidden
            );
            if (detailFields.length) {
                const details = document.createElement("details");
                details.className = "erp-list-card-more";
                const toggle = document.createElement("summary");
                toggle.textContent = "More";
                details.append(toggle);
                const fields = document.createElement("dl");
                fields.className = "erp-list-card-details";
                detailFields.forEach(column => appendCardField(fields, column, cellFor(column)));
                details.append(fields);
                card.append(details);
            }

            const actionColumn = columns.find(column => column.name === "actions");
            const actionCell = actionColumn && cellFor(actionColumn);
            if (actionCell?.textContent.trim()) {
                const actions = document.createElement("details");
                actions.className = "erp-list-card-actions";
                const toggle = document.createElement("summary");
                toggle.textContent = "Actions";
                const links = document.createElement("div");
                links.className = "erp-list-card-action-items";
                Array.from(actionCell.children).forEach(item => {
                    const clone = item.cloneNode(true);
                    clone.removeAttribute("id");
                    clone.querySelectorAll("[id]").forEach(element => element.removeAttribute("id"));
                    links.append(clone);
                });
                actions.append(toggle, links);
                card.append(actions);
            }
            cardList.append(card);
        });
    }

    function appendCardField(list, column, cell) {
        const term = document.createElement("dt");
        term.textContent = column.label;
        const description = document.createElement("dd");
        description.textContent = cell?.textContent.trim() || "—";
        list.append(term, description);
    }

    function applyColumnPriorities() {
        const priorityLimit = window.innerWidth < 576
            ? 1
            : window.innerWidth < 1024 ? 2 : 3;
        columns.forEach(column => {
            const hidden = column.defaultHidden || column.userHidden
                || column.priority > priorityLimit;
            if (column.hidden === hidden) return;
            if (hidden) $grid.jqGrid("hideCol", column.name);
            else $grid.jqGrid("showCol", column.name);
            column.hidden = hidden;
        });
    }

    function persistColumnPreferences() {
        const hidden = {};
        const order = [];
        $grid.jqGrid("getGridParam", "colModel").forEach((column) => {
            if (column.name !== "rn" && column.name !== "cb") {
                hidden[column.name] = Boolean(column.userHidden);
                order.push(column.name);
            }
        });
        localStorage.setItem(storageKey, JSON.stringify({hidden, order}));
    }

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
        emptyrecords: "No records found.",
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
            if (!hasLoaded) showListState("loading", "Loading records…");
        },
        loadComplete(data) {
            hasLoaded = true;
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
            window.history.replaceState(window.history.state, "", currentUrl);
            updatePager(Number(data.page) || 1, Number(data.total) || 1);
            const first = data.records ? ((data.page - 1) * Number($grid.jqGrid("getGridParam", "rowNum"))) + 1 : 0;
            const last = data.records ? Math.min(first + Number($grid.jqGrid("getGridParam", "rowNum")) - 1, data.records) : 0;
            root.querySelector("[data-view-range]").textContent = `View ${first} - ${last} of ${data.records}`;
            persistColumnPreferences();
            renderMobileCards();
            if (Number(data.records) > 0) {
                clearListState();
            } else {
                showListState("empty", "No records found");
            }
        },
        loadError() {
            hasLoaded = true;
            showListState("error", "Could not load records. Retry.");
            const retry = document.createElement("button");
            retry.className = "btn btn-sm btn-outline-primary";
            retry.type = "button";
            retry.textContent = "Retry";
            retry.addEventListener("click", () => $grid.trigger("reloadGrid"));
            listState.append(retry);
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
                const priorityLimit = window.innerWidth < 1024 ? 2 : 3;
                const gridColumns = this.jqGrid("getGridParam", "colModel");
                gridColumns.forEach((gridColumn) => {
                    const column = columns.find(item => item.name === gridColumn.name);
                    if (column && column.priority <= priorityLimit) {
                        column.userHidden = Boolean(gridColumn.hidden);
                    }
                });
                persistColumnPreferences();
                scheduleGridResize();
            },
        });
    });

    function resizeGrid() {
        if (window.innerWidth < 576) return;
        const gridWrap = root.querySelector(".erp-list-grid-wrap");
        const wrapper = root.querySelector(".ui-jqgrid");
        const header = root.querySelector(".ui-jqgrid-hdiv");
        const style = getComputedStyle(gridWrap);
        const width = gridWrap.clientWidth
            - Number.parseFloat(style.paddingLeft)
            - Number.parseFloat(style.paddingRight);
        if (!wrapper || !header || width < 1) return;
        applyColumnPriorities();
        $grid.jqGrid("setGridWidth", width, true);
        const height = Math.max(100, wrapper.getBoundingClientRect().height - header.getBoundingClientRect().height - 1);
        $grid.jqGrid("setGridHeight", height);
    }

    let resizeTimer;
    const scheduleGridResize = () => {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(resizeGrid, 100);
    };
    $(window).off("resize.erpListPage").on("resize.erpListPage", scheduleGridResize);
    window.setTimeout(resizeGrid, 0);
});
