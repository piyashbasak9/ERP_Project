document.addEventListener("submit", async event => {
    const form = event.target;
    if (!form.matches("[data-reconcile-form]")) return;
    event.preventDefault();
    const response = await fetch(form.action, {
        method: "POST",
        body: new FormData(form),
        headers: {
            "X-CSRFToken": form.querySelector("[name=csrfmiddlewaretoken]").value,
            "Accept": "application/json"
        }
    });
    const body = await response.json();
    if (window.handleAuthChallenge(body)) return;
    if (!response.ok || !body.success) {
        window.notify.error(body.message || "The sheet could not be reconciled.");
        return;
    }
    window.notify.success(body.message);
    window.location.reload();
});
