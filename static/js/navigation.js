(function () {
    function syncHeader(event) {
        const currentHeader = document.querySelector("#erp-header");
        const incomingHeader = event.detail.newBody.querySelector("#erp-header");
        if (!currentHeader || !incomingHeader) return;

        const currentMenu = document.querySelector("#erp-menu-bar .erp-menu-list");
        const incomingMenu = event.detail.newBody.querySelector("#erp-menu-bar .erp-menu-list");
        if (currentMenu && incomingMenu) {
            currentMenu.replaceWith(incomingMenu.cloneNode(true));
        }

        const currentBranch = document.querySelector("#active-branch");
        const incomingBranch = event.detail.newBody.querySelector("#active-branch");
        if (currentBranch && incomingBranch) {
            currentBranch.value = incomingBranch.value;
        }

        const currentNotifications = currentHeader.querySelector(".quick-notifications");
        const incomingNotifications = incomingHeader.querySelector(".quick-notifications");
        const currentCount = currentNotifications?.querySelector(".erp-unread-count");
        const incomingCount = incomingNotifications?.querySelector(".erp-unread-count");
        if (currentNotifications && incomingNotifications) {
            currentNotifications.setAttribute(
                "aria-label",
                incomingNotifications.getAttribute("aria-label")
            );
            if (currentCount && incomingCount) {
                currentCount.textContent = incomingCount.textContent;
            } else if (currentCount) {
                currentCount.remove();
            } else if (incomingCount) {
                currentNotifications.append(incomingCount.cloneNode(true));
            }
        }
    }

    const menuBreakpoint = window.matchMedia("(max-width: 1023.98px)");
    const menuToggle = document.querySelector(".erp-menu-toggle");
    const menu = document.querySelector("#erpMenu");
    const headerActions = document.querySelector(".erp-header-actions");
    const actionsToggle = document.querySelector(".erp-actions-toggle");
    const menuBackdrop = document.createElement("button");
    menuBackdrop.className = "erp-menu-backdrop";
    menuBackdrop.type = "button";
    menuBackdrop.setAttribute("aria-label", "Close navigation menu");
    menuBackdrop.hidden = true;
    document.body.append(menuBackdrop);

    function setQuickActionsOpen(open) {
        if (!headerActions || !actionsToggle) return;
        headerActions.classList.toggle("show-quick-actions", open);
        actionsToggle.setAttribute("aria-expanded", String(open));
    }

    function positionBranchSwitcher() {
        const branchForm = document.querySelector(".erp-branch-form");
        const menuTools = document.querySelector("#erpMenuMobileTools");
        const slot = document.querySelector("[data-branch-switcher-slot]");
        if (!branchForm || !menuTools || !slot) return;

        if (menuBreakpoint.matches) {
            menuTools.append(branchForm);
        } else {
            slot.before(branchForm);
        }
    }

    function hideMenu() {
        if (menu?.classList.contains("show") && window.bootstrap?.Collapse) {
            window.bootstrap.Collapse.getOrCreateInstance(menu).hide();
        }
    }

    document.addEventListener("turbo:before-render", syncHeader);
    document.addEventListener("turbo:load", function () {
        document.querySelectorAll("[data-popup], [data-popup-close]")
            .forEach(element => element.setAttribute("data-turbo", "false"));

        positionBranchSwitcher();
        setQuickActionsOpen(false);
        const responsiveMenu = document.querySelector("#erpMenu.show");
        if (responsiveMenu && window.bootstrap?.Collapse) {
            window.bootstrap.Collapse.getOrCreateInstance(responsiveMenu).hide();
        }
    });

    positionBranchSwitcher();
    menuBackdrop.addEventListener("click", hideMenu);
    actionsToggle?.addEventListener("click", function () {
        setQuickActionsOpen(actionsToggle.getAttribute("aria-expanded") !== "true");
    });
    document.addEventListener("click", function (event) {
        if (!event.target.closest(".erp-header-actions")) {
            setQuickActionsOpen(false);
        }
    });

    document.addEventListener("shown.bs.collapse", function (event) {
        if (event.target !== menu) return;
        setQuickActionsOpen(false);
        menu?.closest(".erp-menu-bar")?.classList.add("is-open");
        document.body.classList.add("erp-menu-open");
        menuBackdrop.hidden = false;
        menu?.querySelector(".erp-menu-link")?.focus();
        window.dispatchEvent(new Event("resize"));
    });

    document.addEventListener("hidden.bs.collapse", function (event) {
        if (event.target !== menu) return;
        menu?.closest(".erp-menu-bar")?.classList.remove("is-open");
        document.body.classList.remove("erp-menu-open");
        menuBackdrop.hidden = true;
        menuToggle?.focus();
        window.dispatchEvent(new Event("resize"));
    });

    document.addEventListener("show.bs.dropdown", function (event) {
        const group = event.target.closest?.("#erpMenu .erp-menu-list > .dropdown");
        if (!group || !window.bootstrap?.Dropdown) return;
        document.querySelectorAll("#erpMenu .erp-menu-list > .dropdown.show")
            .forEach(sibling => {
                if (sibling !== group) {
                    window.bootstrap.Dropdown.getOrCreateInstance(
                        sibling.querySelector("[data-bs-toggle='dropdown']")
                    ).hide();
                }
            });
    });

    document.addEventListener("keydown", function (event) {
        if (event.key === "Escape") setQuickActionsOpen(false);
        if (!menu?.classList.contains("show") || !menuBreakpoint.matches) return;

        if (event.key === "Escape") {
            event.preventDefault();
            hideMenu();
            return;
        }
        if (event.key !== "Tab") return;

        const focusable = Array.from(menu.querySelectorAll(
            "a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex='-1'])"
        )).filter(element => element.getClientRects().length);
        if (!focusable.length) {
            event.preventDefault();
            menuToggle?.focus();
            return;
        }

        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && (document.activeElement === first || !menu.contains(document.activeElement))) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && (document.activeElement === last || !menu.contains(document.activeElement))) {
            event.preventDefault();
            first.focus();
        }
    });

    menuBreakpoint.addEventListener("change", function () {
        positionBranchSwitcher();
        if (!menuBreakpoint.matches) hideMenu();
    });

    window.erpVisit = function (target) {
        if (window.Turbo) {
            window.Turbo.visit(target);
        } else {
            window.location.assign(target);
        }
    };

    window.erpReloadPage = function () {
        if (window.Turbo) {
            window.Turbo.visit(window.location.href, {action: "replace"});
        } else {
            window.location.reload();
        }
    };
})();
