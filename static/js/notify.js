(function () {
    'use strict';

    const DELAY_MS = 5000;
    const MAX_TOASTS = 3;
    const CLASSES = {
        success: 'success',
        error: 'danger',
        warning: 'warning',
        info: 'info'
    };

    function container() {
        return document.getElementById('toastContainer');
    }

    function show(level, message) {
        const target = container();
        if (!target || !window.bootstrap || typeof message !== 'string') {
            return;
        }
        while (target.children.length >= MAX_TOASTS) {
            target.firstElementChild.remove();
        }

        const toast = document.createElement('div');
        toast.className = 'toast align-items-center text-bg-' + (CLASSES[level] || CLASSES.info) + ' border-0';
        toast.setAttribute('role', 'status');
        toast.setAttribute('aria-live', 'polite');
        toast.setAttribute('aria-atomic', 'true');

        const row = document.createElement('div');
        row.className = 'd-flex';
        const body = document.createElement('div');
        body.className = 'toast-body';
        body.textContent = message;
        const close = document.createElement('button');
        close.type = 'button';
        close.className = 'btn-close btn-close-white me-2 m-auto';
        close.setAttribute('data-bs-dismiss', 'toast');
        close.setAttribute('aria-label', 'Close');
        row.append(body, close);
        toast.append(row);
        target.append(toast);
        toast.addEventListener('hidden.bs.toast', function () {
            toast.remove();
        }, { once: true });
        new window.bootstrap.Toast(toast, { delay: DELAY_MS, autohide: true }).show();
    }

    window.notify = {
        success: function (message) { show('success', message); },
        error: function (message) { show('error', message); },
        warning: function (message) { show('warning', message); },
        info: function (message) { show('info', message); }
    };

    document.addEventListener('DOMContentLoaded', function () {
        if (!window.bootstrap) {
            return;
        }
        document.querySelectorAll('#toastContainer .toast').forEach(function (toast) {
            toast.addEventListener('hidden.bs.toast', function () {
                toast.remove();
            }, { once: true });
            new window.bootstrap.Toast(toast, { delay: DELAY_MS, autohide: true }).show();
        });
    });
})();
