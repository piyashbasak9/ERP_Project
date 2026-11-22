(function () {
    function syncHeader(event) {
        const currentHeader = document.querySelector("#erp-header");
        const incomingHeader = event.detail.newBody.querySelector("#erp-header");
        if (!currentHeader || !incomingHeader) return;

        const currentMenu = currentHeader.querySelector(".erp-menu-list");
        const incomingMenu = incomingHeader.querySelector(".erp-menu-list");
        if (currentMenu && incomingMenu) {
            currentMenu.replaceWith(incomingMenu.cloneNode(true));
        }

        const currentBranch = currentHeader.querySelector("#active-branch");
        const incomingBranch = incomingHeader.querySelector("#active-branch");
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

    document.addEventListener("turbo:before-render", syncHeader);
    document.addEventListener("turbo:load", function () {
        document.querySelectorAll("[data-popup], [data-popup-close]")
            .forEach(element => element.setAttribute("data-turbo", "false"));

        const responsiveMenu = document.querySelector("#erpMenu.show");
        if (responsiveMenu && window.bootstrap?.Collapse) {
            window.bootstrap.Collapse.getOrCreateInstance(responsiveMenu).hide();
        }
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
