const path = require("node:path");
const {chromium} = require("playwright");

async function main() {
    const baseUrl = process.env.ERP_E2E_BASE_URL;
    const cookieName = process.env.ERP_E2E_COOKIE_NAME;
    const sessionCookie = process.env.ERP_E2E_SESSION_COOKIE;
    const paths = process.env.ERP_E2E_PATHS.split(",");
    const screenshotDirectory = process.env.ERP_E2E_SCREENSHOT_DIR;
    const browser = await chromium.launch({headless: true});

    try {
        const context = await browser.newContext();
        await context.addCookies([{
            name: cookieName,
            value: sessionCookie,
            url: baseUrl,
            httpOnly: true,
            sameSite: "Lax",
        }]);

        for (const viewport of [{width: 1366, height: 768}, {width: 1920, height: 1080}]) {
            for (const route of paths) {
                const page = await context.newPage();
                page.setDefaultTimeout(5000);
                await page.setViewportSize(viewport);
                const response = await page.goto(new URL(route, baseUrl).toString(), {
                    waitUntil: "networkidle",
                });
                if (!response || !response.ok()) {
                    throw new Error(`${route} returned HTTP ${response ? response.status() : "no response"}`);
                }
                await page.locator(".ui-jqgrid-bdiv").waitFor();
                await page.waitForFunction(() => {
                    const grid = document.querySelector(".ui-jqgrid-bdiv");
                    return grid && grid.clientHeight > 100;
                });
                if (route === paths[1] && viewport.width === 1366) {
                    await page.locator("[data-page-next]").click();
                    await page.waitForFunction(() => new URL(location.href).searchParams.get("page") === "2");
                    await page.locator("[data-page-first]").click();
                    await page.waitForFunction(() => new URL(location.href).searchParams.get("page") === "1");
                    await page.locator("[data-page-size]").selectOption("50");
                    await page.waitForFunction(() => new URL(location.href).searchParams.get("rows") === "50");
                    await page.locator("[data-page-size]").selectOption("20");
                    await page.waitForFunction(() => new URL(location.href).searchParams.get("rows") === "20");
                }

                const metrics = await page.evaluate(() => {
                    const main = document.querySelector("main.main-content").getBoundingClientRect();
                    const listPage = document.querySelector(".erp-list-page").getBoundingClientRect();
                    const gridElement = document.querySelector(".erp-list-grid-wrap");
                    const grid = gridElement.getBoundingClientRect();
                    const gridStyle = getComputedStyle(gridElement);
                    const expectedGridWidth = grid.width
                        - parseFloat(gridStyle.paddingLeft)
                        - parseFloat(gridStyle.paddingRight);
                    const jqGrid = document.querySelector(".erp-list-grid-wrap > .ui-jqgrid").getBoundingClientRect();
                    const pagerElement = document.querySelector("[data-grid-pager]");
                    const pager = pagerElement.getBoundingClientRect();
                    return {
                        viewportWidth: window.innerWidth,
                        documentWidth: document.documentElement.scrollWidth,
                        mainWidth: main.width,
                        listPageWidth: listPage.width,
                        gridHeight: grid.height,
                        gridWidth: jqGrid.width,
                        gridWidthGap: Math.abs(expectedGridWidth - jqGrid.width),
                        mainHeight: main.height,
                        gridBottomGap: Math.abs(main.bottom - grid.bottom),
                        pagerHeight: pager.height,
                        pagerText: pagerElement.textContent.trim(),
                        pagerButtons: Array.from(pagerElement.querySelectorAll("[data-page-first], [data-page-previous], [data-page-next], [data-page-last]"))
                            .map((button) => ({
                                label: button.getAttribute("aria-label"),
                                disabled: button.disabled,
                            })),
                    };
                });
                if (metrics.documentWidth > metrics.viewportWidth) {
                    throw new Error(`${route} has horizontal page scrolling at ${viewport.width}px: ${JSON.stringify(metrics)}`);
                }
                if (Math.abs(metrics.mainWidth - metrics.viewportWidth) > 2) {
                    throw new Error(`${route} main content does not fill the viewport: ${JSON.stringify(metrics)}`);
                }
                if (metrics.gridHeight < 250 || metrics.gridBottomGap > 2) {
                    throw new Error(`${route} grid does not fill the remaining height: ${JSON.stringify(metrics)}`);
                }
                if (metrics.gridWidthGap > 2) {
                    throw new Error(`${route} grid does not fill the available width: ${JSON.stringify(metrics)}`);
                }
                if (metrics.pagerHeight > 40 || !metrics.pagerText.includes("Page")
                    || metrics.pagerButtons.length !== 4
                    || !metrics.pagerButtons.every((button) => button.label)) {
                    throw new Error(`${route} pager is not compact or visible: ${JSON.stringify(metrics)}`);
                }

                const slug = route.split("/").filter(Boolean).join("-") || "branches";
                const screenshotPath = path.join(
                    screenshotDirectory,
                    `${slug}-${viewport.width}x${viewport.height}.png`,
                );
                await page.screenshot({path: screenshotPath});
                console.log(`${route} ${viewport.width}x${viewport.height}: ${JSON.stringify(metrics)} -> ${screenshotPath}`);
                await page.close();
            }
        }
    } finally {
        await browser.close();
    }

    console.log("Desktop layout checks passed");
}

main().catch((error) => {
    console.error(error);
    process.exitCode = 1;
});
