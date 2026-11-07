document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-toggle-product]");
    if (!button) return;

    const cookie = document.cookie.split("; ").find((item) => item.startsWith("csrftoken="));
    button.disabled = true;
    try {
        const response = await fetch(button.dataset.toggleProduct, {
            method: "POST",
            headers: {
                "X-CSRFToken": cookie ? decodeURIComponent(cookie.slice("csrftoken=".length)) : "",
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
        window.location.reload();
    } catch {
        window.notify.error("Product status could not be changed. Check your connection and try again.");
    } finally {
        button.disabled = false;
    }
});
