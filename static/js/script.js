window.handleAuthChallenge = function (body) {
    const target = body && body.login_url;
    if (!target) {
        return false;
    }
    window.location.assign(target);
    return true;
};

document.addEventListener('DOMContentLoaded', function () {
    const csrfMeta = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = csrfMeta ? csrfMeta.content : '';
    if (window.jQuery && csrfToken) {
        window.jQuery.ajaxSetup({
            headers: { 'X-CSRFToken': csrfToken }
        });
    }

    if (!window.jQuery) {
        return;
    }
    window.jQuery(document).ajaxError(function (_event, xhr) {
        if (xhr.status === 401) {
            const next = encodeURIComponent(window.location.pathname + window.location.search);
            window.location.href = '/accounts/login/?next=' + next;
        } else if (xhr.status === 403) {
            if (window.handleAuthChallenge(xhr.responseJSON)) {
                return;
            }
            if (window.notify) {
                window.notify.error('You do not have permission to do that.');
            }
        } else if (xhr.status === 409 && window.notify) {
            window.notify.error('This record changed while you were editing it. Reload and try again.');
        } else if (xhr.status >= 500 && window.notify) {
            const body = xhr.responseJSON || {};
            window.notify.error((body.message || 'Something went wrong.') + (body.request_id ? ' Ref: ' + body.request_id : ''));
        }
    });
});

document.addEventListener('click', function (event) {
    const quickSearchToggle = event.target.closest('[data-quick-search-toggle]');
    if (quickSearchToggle) {
        const quickSearch = document.querySelector('[data-quick-search-form]');
        if (quickSearch) {
            quickSearch.hidden = !quickSearch.hidden;
            if (!quickSearch.hidden) {
                quickSearch.querySelector('input').focus();
            }
        }
    }

    if (event.target.closest('[data-print-window]')) {
        window.print();
    }
});

document.addEventListener('keydown', function (event) {
    if (event.key !== 'Escape') {
        return;
    }
    const quickSearch = document.querySelector('[data-quick-search-form]');
    if (quickSearch && !quickSearch.hidden) {
        quickSearch.hidden = true;
        document.querySelector('[data-quick-search-toggle]')?.focus();
    }
});
