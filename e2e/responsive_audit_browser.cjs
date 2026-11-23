const fs = require("node:fs");
const path = require("node:path");
const playwright = require("playwright");

const viewports = [
    {name: "360x640", width: 360, height: 640},
    {name: "390x844", width: 390, height: 844},
    {name: "412x915", width: 412, height: 915},
    {name: "768x1024", width: 768, height: 1024},
    {name: "1024x768", width: 1024, height: 768},
    {name: "1280x720", width: 1280, height: 720},
    {name: "1366x768", width: 1366, height: 768},
    {name: "1536x864", width: 1536, height: 864},
    {name: "1920x1080", width: 1920, height: 1080},
    {name: "2560x1440", width: 2560, height: 1440},
    {name: "zoom125-1366x768", width: 1092, height: 614, zoom: 1.25},
    {name: "zoom150-1366x768", width: 910, height: 512, zoom: 1.5},
];
const selectedViewports = process.env.ERP_RESPONSIVE_VIEWPORTS
    ? JSON.parse(process.env.ERP_RESPONSIVE_VIEWPORTS)
    : viewports;
const selectedBrowsers = (process.env.ERP_RESPONSIVE_BROWSERS || "chromium,firefox,webkit")
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);
const paths = JSON.parse(process.env.ERP_E2E_PATHS || "[]");
const baseUrl = process.env.ERP_E2E_BASE_URL;
const resultsFile = process.env.ERP_RESPONSIVE_RESULTS_FILE;
const screenshotDirectory = process.env.ERP_RESPONSIVE_SCREENSHOT_DIR;
const failures = [];
const screenshotKeys = new Set();

function addFailure(browser, viewport, route, finding) {
    failures.push({
        browser,
        viewport: viewport.name,
        route,
        finding: String(finding).replaceAll("|", "\\|").replaceAll("\n", " "),
    });
}

async function inspectPage(page, browserName, viewport, route, routeIndex) {
    const issues = await page.evaluate(({mobile, touch, width, height}) => {
        const visible = (element) => {
            const rect = element.getBoundingClientRect();
            const style = getComputedStyle(element);
            return rect.width > 0 && rect.height > 0 && style.display !== "none"
                && style.visibility !== "hidden" && Number(style.opacity) > 0;
        };
        const horizontallyOutside = (rect) => rect.left < -1 || rect.right > width + 1;
        const insideScrollContainer = (element) => {
            let parent = element.parentElement;
            while (parent && parent !== document.body) {
                const style = getComputedStyle(parent);
                if (/(auto|scroll)/.test(`${style.overflow} ${style.overflowX} ${style.overflowY}`)) {
                    return true;
                }
                parent = parent.parentElement;
            }
            return false;
        };
        const clippedByOverflowAncestor = (element) => {
            const rect = element.getBoundingClientRect();
            let parent = element.parentElement;
            while (parent && parent !== document.body) {
                const style = getComputedStyle(parent);
                const parentRect = parent.getBoundingClientRect();
                if (/(auto|scroll|hidden|clip)/.test(style.overflowX)
                    && (rect.left < parentRect.left || rect.right > parentRect.right)) return true;
                if (/(auto|scroll|hidden|clip)/.test(style.overflowY)
                    && (rect.top < parentRect.top || rect.bottom > parentRect.bottom)) return true;
                parent = parent.parentElement;
            }
            return false;
        };
        const findings = [];
        const header = document.querySelector(".erp-header");
        if (header) {
            const expectedHeight = width < 1024 ? 56 : 90;
            const actualHeight = header.getBoundingClientRect().height;
            if (Math.abs(actualHeight - expectedHeight) > 1) {
                findings.push(`shared navbar height mismatch ${Math.round(actualHeight)}px vs ${expectedHeight}px`);
            }
        }
        if (document.documentElement.scrollWidth > width + 1) {
            findings.push(`horizontal page scroll ${document.documentElement.scrollWidth}px > ${width}px`);
        }
        for (const element of document.querySelectorAll("body *")) {
            if (!visible(element)) continue;
            const rect = element.getBoundingClientRect();
            const positioned = ["fixed", "sticky"].includes(getComputedStyle(element).position);
            if ((horizontallyOutside(rect) || (positioned && (rect.top < -1 || rect.bottom > height + 1)))
                && !insideScrollContainer(element)) {
                findings.push(`element outside viewport: ${element.tagName.toLowerCase()}.${String(element.className).split(" ").filter(Boolean).join(".")} (${Math.round(rect.left)},${Math.round(rect.top)},${Math.round(rect.right)},${Math.round(rect.bottom)})`);
            }
            const text = (element.children.length === 0 ? element.textContent : "").trim();
            if (text && getComputedStyle(element).fontSize) {
                const fontSize = Number.parseFloat(getComputedStyle(element).fontSize);
                const minimum = mobile ? 14 : 12;
                if (fontSize < minimum) {
                    findings.push(`small text ${fontSize}px (<${minimum}px): ${text.slice(0, 40)}`);
                }
            }
            if (touch && element.matches("a,button,input,select,textarea,[role=button],[tabindex]:not([tabindex='-1'])")) {
                if (rect.width < 44 || rect.height < 44) {
                    findings.push(`small touch target ${Math.round(rect.width)}x${Math.round(rect.height)}: ${element.tagName.toLowerCase()} ${text.slice(0, 30)}`);
                }
            }
        }
        const toast = document.querySelector("#toastContainer .toast.show");
        if (toast && header) {
            const toastRect = toast.getBoundingClientRect();
            const headerRect = header.getBoundingClientRect();
            if (toastRect.left < headerRect.right && toastRect.right > headerRect.left
                && toastRect.top < headerRect.bottom && toastRect.bottom > headerRect.top) {
                findings.push("toast overlaps header controls");
            }
        }

        const major = [
            [".erp-header", document.querySelector(".erp-header")],
            ["main.main-content", document.querySelector("main.main-content")],
            [".erp-status-bar", document.querySelector(".erp-status-bar")],
            [".erp-page-title", document.querySelector(".erp-page-title")],
            [".erp-filter-panel", document.querySelector(".erp-filter-panel:not([hidden])")],
            [".report-filter-panel", document.querySelector(".report-filter-panel:not([hidden])")],
            [".erp-list-grid-wrap", document.querySelector(".erp-list-grid-wrap")],
            [".erp-grid-status", document.querySelector(".erp-grid-status")],
        ].filter(([, element]) => element && visible(element))
            .filter(([name, element]) => !(
                [".erp-filter-panel", ".report-filter-panel"].includes(name)
                && getComputedStyle(element).position === "fixed"
            ))
            .map(([name, element]) => ({name, rect: element.getBoundingClientRect(), element}));
        for (let left = 0; left < major.length; left += 1) {
            for (let right = left + 1; right < major.length; right += 1) {
                if (major[left].element.contains(major[right].element)
                    || major[right].element.contains(major[left].element)) continue;
                const a = major[left].rect;
                const b = major[right].rect;
                if (a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top) {
                    findings.push(`overlap: ${major[left].name} and ${major[right].name}`);
                }
            }
        }
        for (const selector of [
            ".dropdown-menu.show",
            ".modal.show",
            ".ui-dialog",
            "#toastContainer .toast.show",
            ".erp-menu-bar .navbar-collapse.show",
            ".erp-filter-panel:not([hidden])",
            ".report-filter-panel:not([hidden])",
        ]) {
            for (const element of document.querySelectorAll(selector)) {
                const rect = element.getBoundingClientRect();
                if (visible(element) && (horizontallyOutside(rect) || rect.top < -1
                    || rect.bottom > height + 1 || clippedByOverflowAncestor(element))) {
                    findings.push(`clipped overlay: ${selector}`);
                }
            }
        }
        const modal = document.querySelector(".modal.show");
        if (modal) {
            const dialog = modal.querySelector(".modal-dialog");
            const actions = modal.querySelector(".modal-footer, .erp-popup-actions, .form-actions");
            const rect = (actions || dialog || modal).getBoundingClientRect();
            if (rect.bottom > height || rect.top < 0) findings.push("popup actions extend beyond the viewport");
        }
        const dialog = document.querySelector(".ui-dialog");
        if (dialog && visible(dialog)) {
            const buttons = dialog.querySelector(".ui-dialog-buttonpane") || dialog;
            const rect = buttons.getBoundingClientRect();
            if (rect.left < 0 || rect.right > width || rect.top < 0 || rect.bottom > height) {
                findings.push("popup actions extend beyond the viewport");
            }
        }

        const gridWrap = document.querySelector(".erp-list-grid-wrap");
        const grid = document.querySelector(".erp-list-grid-wrap .ui-jqgrid");
        if (gridWrap && grid && visible(grid) && width >= 576) {
            const style = getComputedStyle(gridWrap);
            const parentWidth = gridWrap.clientWidth
                - Number.parseFloat(style.paddingLeft)
                - Number.parseFloat(style.paddingRight);
            const expectedWidth = width < 1024 ? Math.max(parentWidth, 760) : parentWidth;
            const gridRect = grid.getBoundingClientRect();
            if (Math.abs(gridRect.width - expectedWidth) > 8) {
                findings.push(`grid width mismatch ${Math.round(gridRect.width)}px vs ${Math.round(expectedWidth)}px`);
            }
        }
        const reportCards = document.querySelector(".report-grid-cards");
        if (mobile && reportCards && getComputedStyle(reportCards).display === "none") {
            findings.push("report results are not using mobile cards");
        }
        if (mobile && reportCards) {
            const reportPager = document.querySelector("[data-report-mobile-pager]");
            if (!reportPager || getComputedStyle(reportPager).display === "none") {
                findings.push("report compact pager is hidden on mobile");
            }
        }
        const listCards = document.querySelector("[data-list-cards]");
        if (mobile && listCards && getComputedStyle(listCards).display === "none") {
            findings.push("list results are not using mobile cards");
        }
        return findings;
    }, {
        mobile: viewport.width < 576,
        touch: viewport.width < 1024,
        width: viewport.width,
        height: viewport.height,
    });

    for (const issue of issues) addFailure(browserName, viewport, route, issue);
    const screenshotKey = `${browserName}:${viewport.name}:${routeIndex}`;
    if (issues.length && !screenshotKeys.has(screenshotKey)) {
        screenshotKeys.add(screenshotKey);
        const safePath = path.join(screenshotDirectory, browserName);
        fs.mkdirSync(safePath, {recursive: true});
        await page.screenshot({
            path: path.join(safePath, `${routeIndex}-${viewport.name}.png`),
        }).catch(() => {});
    }
    if (issues.some(issue => issue.includes("popup actions extend beyond the viewport"))) {
        const safePath = path.join(screenshotDirectory, browserName);
        fs.mkdirSync(safePath, {recursive: true});
        await page.screenshot({
            path: path.join(safePath, `${routeIndex}-${viewport.name}-popup.png`),
        }).catch(() => {});
    }
}

async function inspectInteractions(page, browserName, viewport, route, routeIndex, inspectHeader) {
    const narrow = viewport.width < 1024;
    const menuToggle = page.locator(".erp-menu-toggle").first();
    const menu = page.locator("#erpMenu");
    const inspectGridFit = async (menuState) => {
        const fits = await page.evaluate(() => {
            const wrap = document.querySelector(".erp-list-grid-wrap");
            const grid = document.querySelector(".erp-list-grid-wrap .ui-jqgrid");
            if (!wrap || !grid || getComputedStyle(grid).display === "none"
                || window.innerWidth < 576) return true;
            const style = getComputedStyle(wrap);
            const contentWidth = wrap.clientWidth
                - Number.parseFloat(style.paddingLeft)
                - Number.parseFloat(style.paddingRight);
            const expectedWidth = window.innerWidth < 1024
                ? Math.max(contentWidth, 760)
                : contentWidth;
            return Math.abs(grid.getBoundingClientRect().width - expectedWidth) <= 8;
        });
        if (!fits) {
            addFailure(
                browserName,
                viewport,
                route,
                `grid did not resize when the menu ${menuState}`,
            );
        }
    };
    const openMenu = async () => {
        if (await menuToggle.isVisible().catch(() => false)
            && await menuToggle.getAttribute("aria-expanded", {timeout: 500}).catch(() => null) !== "true") {
            await menuToggle.click({timeout: 1500}).catch(() => {});
            await page.locator("#erpMenu.show").waitFor({state: "visible", timeout: 1500}).catch(() => {});
            await page.waitForFunction(() => {
                const drawer = document.querySelector(".erp-menu-bar");
                return drawer?.classList.contains("is-open")
                    && drawer.getBoundingClientRect().left >= -1;
            }, null, {timeout: 1500}).catch(() => {});
        }
    };
    const closeMenu = async () => {
        if (await menuToggle.count() && await menuToggle.getAttribute("aria-expanded", {timeout: 500}).catch(() => null) === "true") {
            await page.evaluate(() => {
                const element = document.querySelector("#erpMenu");
                if (element && window.bootstrap?.Collapse) {
                    window.bootstrap.Collapse.getOrCreateInstance(element).hide();
                }
            });
            await page.waitForTimeout(120);
        }
    };
    if (inspectHeader && narrow && await menuToggle.isVisible().catch(() => false)) {
        await openMenu();
        const expanded = await menuToggle.getAttribute("aria-expanded", {timeout: 500}).catch(() => null);
        if (expanded !== "true") {
            addFailure(browserName, viewport, route, "navigation drawer did not set aria-expanded=true");
        }
        await inspectPage(page, browserName, viewport, route, routeIndex);
        await page.waitForTimeout(200);
        await inspectGridFit("opened");
        const trapped = await page.evaluate(() => {
            const menu = document.querySelector("#erpMenu");
            return Boolean(menu && menu.contains(document.activeElement));
        });
        if (!trapped) {
            addFailure(browserName, viewport, route, "navigation drawer did not move focus into the menu");
        }
        await page.keyboard.press("Escape");
        await page.waitForTimeout(100);
        await inspectGridFit("closed");
        if (await menuToggle.getAttribute("aria-expanded", {timeout: 500}).catch(() => null) === "true") {
            addFailure(browserName, viewport, route, "navigation drawer did not close on Escape");
            await closeMenu();
        }
    }

    if (inspectHeader) {
        if (narrow) await openMenu();
        const dropdowns = page.locator(".erp-menu-list .dropdown-toggle, .erp-header-actions .dropdown-toggle");
        const dropdownCount = await dropdowns.count();
        for (let index = 0; index < dropdownCount; index += 1) {
            const dropdown = dropdowns.nth(index);
            if (!await dropdown.isVisible().catch(() => false)) continue;
            await dropdown.click({timeout: 1500}).catch(() => {});
            await page.waitForTimeout(80);
            const dropdownMenu = dropdown.locator("xpath=following-sibling::ul[contains(@class,'dropdown-menu')]");
            if (!await dropdownMenu.isVisible().catch(() => false)) {
                addFailure(browserName, viewport, route, "dropdown menu did not open");
            }
            await inspectPage(page, browserName, viewport, route, routeIndex);
            await page.keyboard.press("Escape");
            await page.waitForTimeout(50);
        }
        if (narrow) await closeMenu();
    }
    if (narrow) await closeMenu();

    const filterToggle = page.locator("[data-filter-toggle]").first();
    if (await filterToggle.isVisible().catch(() => false)) {
        await filterToggle.click({timeout: 1500}).catch(() => {});
        await page.waitForTimeout(80);
        await inspectPage(page, browserName, viewport, route, routeIndex);
        if (await filterToggle.getAttribute("aria-expanded") === "true") {
            await filterToggle.click({timeout: 1500}).catch(() => {});
            await page.waitForTimeout(80);
        }
    }

    const reportFilterToggle = page.locator("[data-report-filter-toggle]").first();
    if (await reportFilterToggle.isVisible().catch(() => false)) {
        await reportFilterToggle.click({timeout: 1500}).catch(() => {});
        await page.waitForTimeout(80);
        const expanded = await reportFilterToggle.getAttribute("aria-expanded");
        const reportFiltersVisible = await page.locator("#reportFilters").isVisible();
        if (expanded !== "true" || !reportFiltersVisible) {
            addFailure(browserName, viewport, route, "report filter panel did not open");
        }
        await inspectPage(page, browserName, viewport, route, routeIndex);
        await reportFilterToggle.click({timeout: 1500}).catch(() => {});
        await page.waitForTimeout(80);
    }

    const popupLink = page.locator("a[data-popup]").first();
    if (await popupLink.isVisible().catch(() => false)) {
        await popupLink.click({timeout: 1500}).catch(() => {});
        await page.waitForSelector(".modal.show", {timeout: 3000}).catch(() => {});
        if (await page.locator(".modal.show").count()) {
            await inspectPage(page, browserName, viewport, route, routeIndex);
            await page.locator(".modal.show [data-popup-dismiss]").click().catch(() => {});
            await page.waitForTimeout(80);
        } else {
            addFailure(browserName, viewport, route, "popup link did not open a modal");
        }
    }

    const confirmLink = page.locator("a[data-confirm]").first();
    if (await confirmLink.isVisible().catch(() => false)) {
        await confirmLink.click({timeout: 1500}).catch(() => {});
        await page.waitForSelector(".ui-dialog", {timeout: 1500}).catch(() => {});
        if (await page.locator(".ui-dialog").isVisible().catch(() => false)) {
            await inspectPage(page, browserName, viewport, route, routeIndex);
            await page.locator(".ui-dialog-buttonpane button").first().click({timeout: 1500}).catch(() => {});
            await page.waitForTimeout(80);
        } else {
            addFailure(browserName, viewport, route, "confirmation popup did not open");
        }
    }

    if (await page.locator(".erp-list-grid-wrap .ui-jqgrid, .report-grid-scroll .ui-jqgrid").count()) {
        const resizedWidth = Math.max(320, viewport.width - 16);
        await page.setViewportSize({width: resizedWidth, height: viewport.height});
        await page.waitForTimeout(160);
        const gridFits = await page.evaluate(() => {
            const listWrap = document.querySelector(".erp-list-grid-wrap");
            const reportWrap = document.querySelector(".report-grid-scroll");
            const wrap = listWrap || reportWrap;
            const grid = wrap?.querySelector(".ui-jqgrid");
            if (!wrap || !grid || getComputedStyle(grid).display === "none"
                || window.innerWidth < 576) return true;
            const style = getComputedStyle(wrap);
            const contentWidth = wrap.clientWidth
                - Number.parseFloat(style.paddingLeft)
                - Number.parseFloat(style.paddingRight);
            const expectedWidth = window.innerWidth < 1024
                ? Math.max(contentWidth, 760)
                : contentWidth;
            return Math.abs(grid.getBoundingClientRect().width - expectedWidth) <= 8;
        });
        if (!gridFits) {
            addFailure(browserName, viewport, route, "grid did not resize with the window");
        }
        await page.setViewportSize({width: viewport.width, height: viewport.height});
        await page.waitForTimeout(100);
    }
}

async function main() {
    const results = {
        browsers: selectedBrowsers,
        viewports: selectedViewports.map((viewport) => viewport.name),
        routes: paths,
        failures,
    };
    fs.mkdirSync(path.dirname(resultsFile), {recursive: true});
    fs.mkdirSync(screenshotDirectory, {recursive: true});

    await Promise.all(selectedBrowsers.map(async (browserName) => {
        const browserType = playwright[browserName];
        if (!browserType) throw new Error(`Unknown Playwright browser: ${browserName}`);
        const browser = await browserType.launch({headless: true});
        try {
            for (const viewport of selectedViewports) {
                const context = await browser.newContext({
                    viewport: {width: viewport.width, height: viewport.height},
                    deviceScaleFactor: viewport.zoom || 1,
                    ...(browserName !== "firefox" && viewport.width < 1024
                        ? {hasTouch: true}
                        : {}),
                });
                await context.addCookies([{
                    name: process.env.ERP_E2E_COOKIE_NAME,
                    value: process.env.ERP_E2E_SESSION_COOKIE,
                    url: baseUrl,
                    httpOnly: true,
                    sameSite: "Lax",
                }]);
                const page = await context.newPage();
                const consoleErrors = [];
                page.on("console", (message) => {
                    if (message.type() === "error") consoleErrors.push(message.text());
                });
                page.on("pageerror", (error) => consoleErrors.push(error.message));

                const sharedNavSizes = new Map();
                for (const [routeIndex, route] of paths.entries()) {
                    consoleErrors.length = 0;
                    let response;
                    try {
                        response = await page.goto(new URL(route, baseUrl).toString(), {
                            waitUntil: "domcontentloaded",
                            timeout: 15000,
                        });
                        await page.waitForTimeout(100);
                    } catch (error) {
                        addFailure(browserName, viewport, route, `navigation failed: ${error.message}`);
                        continue;
                    }
                    if (!response || !response.ok()) {
                        addFailure(browserName, viewport, route, `HTTP ${response ? response.status() : "no response"}`);
                    }
                    if (route === "/" || route === "/branch/") {
                        const headerSize = await page.evaluate(() => {
                            const header = document.querySelector("#erp-header");
                            if (!header) return null;
                            const dimensions = (element) => {
                                if (!element) return null;
                                const rect = element.getBoundingClientRect();
                                return [rect.height];
                            };
                            const typography = (element) => {
                                if (!element) return null;
                                const style = getComputedStyle(element);
                                return [style.fontFamily, style.fontSize, style.lineHeight];
                            };
                            const headerRect = header.getBoundingClientRect();
                            return {
                                header: [headerRect.width, headerRect.height],
                                headerTypography: typography(header),
                                brand: dimensions(header.querySelector(".erp-header-organization")),
                                brandTypography: typography(header.querySelector(".navbar-brand")),
                                menu: dimensions(header.querySelector(".erp-menu-bar")),
                                menuTypography: typography(header.querySelector(".erp-menu-link")),
                                actions: dimensions(header.querySelector(".erp-header-actions")),
                                user: dimensions(header.querySelector(".erp-user-pill")),
                                userTypography: typography(header.querySelector(".erp-user-pill")),
                            };
                        });
                        if (headerSize) sharedNavSizes.set(route, headerSize);
                    }
                    await inspectPage(page, browserName, viewport, route, routeIndex);
                    await inspectInteractions(
                        page,
                        browserName,
                        viewport,
                        route,
                        routeIndex,
                        routeIndex === 0,
                    );
                    for (const message of consoleErrors) {
                        addFailure(browserName, viewport, route, `console error: ${message}`);
                    }
                }
                const dashboardHeader = sharedNavSizes.get("/");
                const branchHeader = sharedNavSizes.get("/branch/");
                const differentHeaderMetrics = dashboardHeader && branchHeader
                    ? Object.keys(dashboardHeader).filter((key) => {
                        const dashboardMetric = dashboardHeader[key];
                        const branchMetric = branchHeader[key];
                        if (!dashboardMetric || !branchMetric) return dashboardMetric !== branchMetric;
                        return dashboardMetric.some((value, index) => (
                            typeof value === "number" && typeof branchMetric[index] === "number"
                                ? Math.abs(value - branchMetric[index]) > 1
                                : value !== branchMetric[index]
                        ));
                    })
                    : [];
                if (differentHeaderMetrics.length) {
                    const details = Object.fromEntries(differentHeaderMetrics.map((key) => [
                        key,
                        {dashboard: dashboardHeader[key], branch: branchHeader[key]},
                    ]));
                    addFailure(
                        browserName,
                        viewport,
                        "/branch/",
                        `navbar metrics differ from dashboard: ${JSON.stringify(details)}`,
                    );
                }
                await context.close();
                fs.writeFileSync(resultsFile, JSON.stringify(results, null, 2));
            }
        } finally {
            await browser.close();
        }
    }));

    fs.writeFileSync(resultsFile, JSON.stringify(results, null, 2));
    console.log(`Visited ${paths.length} routes; ${failures.length} finding(s).`);
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
