(() => {
    const csrf = () => document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
    const warning = document.getElementById("unsaved-warning");
    let dirty = false;
    const updateDirty = () => {
        dirty = [...document.querySelectorAll("[data-collection-row] [data-original]")]
            .some(input => input.value !== input.dataset.original);
        warning?.classList.toggle("d-none", !dirty);
    };
    const updateTotal = () => {
        let total = 0;
        document.querySelectorAll("[data-collection-row]").forEach(row => {
            total += Number(row.querySelector('[name="collected_amount"]')?.value || 0);
            total += Number(row.querySelector('[name="savings_amount"]')?.value || 0);
        });
        const totalNode = document.getElementById("live-total");
        if (totalNode) totalNode.textContent = total.toFixed(2);
    };
    document.addEventListener("input", event => {
        if (event.target.matches("[data-original]")) {
            updateDirty();
            updateTotal();
        }
    });
    window.addEventListener("beforeunload", event => {
        if (dirty) {
            event.preventDefault();
            event.returnValue = "";
        }
    });
    document.addEventListener("submit", async event => {
        const form = event.target;
        if (!form.matches("[data-entry-form], [data-sheet-action]")) return;
        event.preventDefault();
        if (form.matches("[data-sheet-action]") && dirty) {
            window.notify.error("Save all collection changes before changing the sheet status.");
            return;
        }
        const response = await fetch(form.action, {
            method: "POST",
            body: new FormData(form),
            headers: {"X-CSRFToken": csrf(), "Accept": "application/json"}
        });
        const body = await response.json();
        if (window.handleAuthChallenge(body)) return;
        if (!response.ok || !body.success) {
            window.notify.error(body.message || "The collection change could not be saved.");
            return;
        }
        if (form.matches("[data-entry-form]")) {
            form.closest("[data-collection-row]")
                ?.querySelectorAll("[data-original]")
                .forEach(input => { input.dataset.original = input.value; });
            updateDirty();
            form.querySelector("button[type=submit]")?.blur();
        } else {
            window.location.reload();
        }
        window.notify.success(body.message);
    });
})();
