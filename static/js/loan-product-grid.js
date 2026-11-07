document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-toggle-product]");
    if (!button) return;

    button.disabled = true;
    const csrf = document.cookie.split("; ")
        .find((item) => item.startsWith("csrftoken="))
        ?.slice("csrftoken=".length);
    try {
        const response = await fetch(button.dataset.toggleProduct, {
            method: "POST",
            headers: {
                "X-CSRFToken": csrf ? decodeURIComponent(csrf) : "",
                "Accept": "application/json",
            },
        });
        const body = await response.json();
        if (window.handleAuthChallenge(body)) return;
        if (!response.ok) {
            window.notify.error(body.message || "Product status could not be changed.");
            return;
        }
        window.notify.success(body.message);
        document.querySelector("[data-grid-refresh]")?.click();
    } catch (error) {
        console.error("Loan product status update failed.", error);
        window.notify.error("Product status could not be changed.");
    } finally {
        button.disabled = false;
    }
});
