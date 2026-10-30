(function ($) {
    const useJqueryUi = $ && $.fn.dialog;
    let $confirmDialog = null;
    let confirmTarget = null;
    let popupModal = null;
    let popupElement = null;
    let popupUrl = null;
    let formDirty = false;

    function ensurePopupModal() {
        if (popupElement) {
            return;
        }
        popupElement = document.createElement('div');
        popupElement.className = 'modal fade';
        popupElement.tabIndex = -1;
        popupElement.setAttribute('aria-hidden', 'true');
        popupElement.innerHTML = '<div class="modal-dialog modal-dialog-centered modal-dialog-scrollable modal-fullscreen-sm-down modal-lg"><div class="modal-content"><div class="modal-header"><h2 class="modal-title fs-5"></h2><button type="button" class="btn-close" aria-label="Close" data-popup-dismiss></button></div><div class="modal-body"></div></div></div>';
        document.body.appendChild(popupElement);
        popupModal = new bootstrap.Modal(popupElement, {backdrop: 'static', keyboard: false});
        popupElement.addEventListener('hide.bs.modal', function (event) {
            if (formDirty && !window.confirm('Discard your unsaved changes?')) {
                event.preventDefault();
            }
        });
        popupElement.addEventListener('hidden.bs.modal', function () {
            popupElement.querySelector('.modal-body').replaceChildren();
            formDirty = false;
        });
    }

    function notifyError(message) {
        if (window.notify) {
            window.notify.error(message);
        }
    }

    function csrfToken(form) {
        const cookie = document.cookie.split('; ').find(function (part) {
            return part.startsWith('csrftoken=');
        });
        return cookie
            ? decodeURIComponent(cookie.slice('csrftoken='.length))
            : (form.querySelector('[name=csrfmiddlewaretoken]') || {}).value || '';
    }

    function refreshGrid() {
        const grids = document.querySelectorAll('table.ui-jqgrid-btable');
        if ($ && grids.length) {
            grids.forEach(function (grid) {
                const $grid = $(grid);
                const currentPage = Number($grid.jqGrid('getGridParam', 'page')) || 1;
                $grid.jqGrid('setGridParam', {page: currentPage}).trigger('reloadGrid');
            });
        } else {
            window.location.reload();
        }
    }

    function clearFieldErrors(form) {
        form.querySelectorAll('.is-invalid').forEach(function (field) {
            field.classList.remove('is-invalid');
        });
        form.querySelectorAll('[data-popup-field-error]').forEach(function (error) {
            error.remove();
        });
        form.querySelectorAll('[data-popup-form-error]').forEach(function (error) {
            error.remove();
        });
    }

    function showFieldErrors(form, errors) {
        Object.entries(errors || {}).forEach(function (entry) {
            const name = entry[0];
            const messages = entry[1];
            const field = form.querySelector('[name="' + CSS.escape(name) + '"]');
            if (!field) {
                const error = document.createElement('div');
                error.className = 'alert alert-danger';
                error.dataset.popupFormError = '';
                error.textContent = messages.join(' ');
                form.prepend(error);
                return;
            }
            field.classList.add('is-invalid');
            const error = document.createElement('div');
            error.className = 'invalid-feedback d-block';
            error.dataset.popupFieldError = '';
            error.textContent = messages.join(' ');
            field.insertAdjacentElement('afterend', error);
        });
    }

    async function openPopup(link) {
        ensurePopupModal();
        const title = link.getAttribute('data-popup-title') || link.textContent.trim() || 'Details';
        popupUrl = new URL(link.href, window.location.href);
        popupUrl.searchParams.set('popup', '1');
        popupElement.querySelector('.modal-title').textContent = title;
        popupElement.querySelector('.modal-body').innerHTML = '<div class="d-flex justify-content-center p-5"><div class="spinner-border" role="status"><span class="visually-hidden">Loading</span></div></div>';
        popupModal.show();
        try {
            const response = await fetch(popupUrl, {
                credentials: 'same-origin',
                headers: {
                    'Accept': 'text/html',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            if (response.status === 401) {
                const result = await response.json();
                popupModal.hide();
                window.location.assign('/accounts/login/?next=' + encodeURIComponent(window.location.pathname));
                throw new Error(result.message || 'Your session has expired. Please sign in again.');
            }
            const contentType = response.headers.get('content-type') || '';
            if (!response.ok || !contentType.includes('text/html')) {
                throw new Error('The form could not be loaded. Please try again.');
            }
            popupElement.querySelector('.modal-body').innerHTML = await response.text();
            const form = popupElement.querySelector('form');
            if (form) {
                if (!form.getAttribute('action')) {
                    form.setAttribute('action', popupUrl.href);
                } else {
                    const action = new URL(form.getAttribute('action'), popupUrl);
                    action.searchParams.set('popup', '1');
                    form.setAttribute('action', action.href);
                }
                form.addEventListener('input', function () {
                    formDirty = true;
                });
                form.addEventListener('change', function () {
                    formDirty = true;
                });
                const firstField = form.querySelector('input:not([type=hidden]), select, textarea');
                if (firstField) {
                    firstField.focus({preventScroll: true});
                }
            }
        } catch (error) {
            popupElement.querySelector('.modal-body').replaceChildren();
            popupModal.hide();
            notifyError(error.message);
        }
    }

    async function submitPopupForm(form) {
        clearFieldErrors(form);
        const submit = form.querySelector('[type=submit]');
        if (submit) {
            submit.disabled = true;
            submit.dataset.originalText = submit.innerHTML;
            submit.innerHTML = '<span class="spinner-border spinner-border-sm me-2" aria-hidden="true"></span>Saving…';
        }
        try {
            const response = await fetch(form.action || popupUrl.href, {
                method: (form.method || 'POST').toUpperCase(),
                body: new FormData(form),
                credentials: 'same-origin',
                headers: {
                    'Accept': 'application/json',
                    'X-CSRFToken': csrfToken(form),
                    'X-Requested-With': 'XMLHttpRequest'
                }
            });
            const result = await response.json();
            if (response.status === 401) {
                popupModal.hide();
                window.location.assign('/accounts/login/?next=' + encodeURIComponent(window.location.pathname));
                return;
            }
            if (!response.ok || !result.success) {
                showFieldErrors(form, result.errors);
                notifyError(result.message || 'Please correct the highlighted fields.');
                return;
            }
            formDirty = false;
            popupModal.hide();
            if (window.notify) {
                window.notify.success(result.message);
            }
            refreshGrid();
        } catch (error) {
            notifyError(error.message || 'The request failed. Please try again.');
        } finally {
            if (submit) {
                submit.disabled = false;
                submit.innerHTML = submit.dataset.originalText;
            }
        }
    }

    function sendDeleteRequest(link) {
        const token = csrfToken(document);
        const $error = $confirmDialog && $confirmDialog.find('[data-confirm-error]');
        if ($error) {
            $error.text('').addClass('d-none');
        }

        fetch(link.href, {
            method: 'POST',
            credentials: 'same-origin',
            headers: {
                'Accept': 'application/json',
                'Content-Type': 'application/json',
                'X-CSRFToken': token,
                'X-Requested-With': 'XMLHttpRequest'
            }
        }).then(function (response) {
            return response.json().catch(function () {
                throw new Error('The request failed. Please try again.');
            }).then(function (result) {
                if (!response.ok || !result.success) {
                    throw new Error(result.message || 'The item could not be deleted.');
                }
                window.location.reload();
            });
        }).catch(function (error) {
            if ($error) {
                $error.text(error.message).removeClass('d-none');
                return;
            }
            notifyError(error.message);
        });
    }

    function confirmDelete(link) {
        if (!useJqueryUi) {
            if (window.confirm(link.getAttribute('data-confirm-message') || 'Are you sure you want to delete this item?')) {
                sendDeleteRequest(link);
            }
            return;
        }

        if (!$confirmDialog) {
            $confirmDialog = $('<div class="app-confirm-dialog"><div class="app-confirm-content"><span class="app-confirm-icon" aria-hidden="true">!</span><div><p class="app-confirm-message"></p><div class="app-confirm-error alert alert-danger d-none" data-confirm-error role="alert"></div></div></div></div>')
                .appendTo('body')
                .dialog({
                    autoOpen: false,
                    modal: true,
                    resizable: false,
                    width: Math.min(460, window.innerWidth - 32),
                    dialogClass: 'app-confirm-window',
                    buttons: []
                });
        }

        confirmTarget = link;
        $confirmDialog.dialog('option', 'buttons', [
            {
                text: 'Cancel',
                class: 'btn btn-outline-secondary',
                click: function () {
                    $(this).dialog('close');
                }
            },
            {
                text: link.getAttribute('data-confirm-button') || 'Confirm',
                class: 'btn btn-danger',
                click: function () {
                    if (confirmTarget) {
                        sendDeleteRequest(confirmTarget);
                    }
                }
            }
        ]);
        $confirmDialog.find('.app-confirm-message').text(
            link.getAttribute('data-confirm-message') || 'Are you sure you want to delete this item?'
        );
        $confirmDialog.dialog('option', 'title', link.getAttribute('data-confirm-title') || 'Please confirm');
        $confirmDialog.dialog('open');
    }

    document.addEventListener('click', function (event) {
        const target = event.target instanceof Element ? event.target : null;
        if (!target) {
            return;
        }

        const dismiss = target.closest('[data-popup-dismiss], [data-popup-close]');
        if (dismiss && popupModal && popupElement.contains(dismiss)) {
            event.preventDefault();
            popupModal.hide();
            return;
        }

        const confirmLink = target.closest('a[data-confirm]');
        if (confirmLink) {
            if (
                (event.which && event.which !== 1) ||
                event.ctrlKey ||
                event.metaKey ||
                event.shiftKey ||
                event.altKey
            ) {
                return;
            }
            event.preventDefault();
            confirmDelete(confirmLink);
            return;
        }

        const link = target.closest('a[data-popup]');
        if (link) {
            if (
                (event.which && event.which !== 1) ||
                event.ctrlKey ||
                event.metaKey ||
                event.shiftKey ||
                event.altKey
            ) {
                return;
            }
            event.preventDefault();
            openPopup(link);
        }
    });

    document.addEventListener('submit', function (event) {
        const form = event.target instanceof HTMLFormElement ? event.target : null;
        if (form && popupElement && popupElement.contains(form)) {
            event.preventDefault();
            submitPopupForm(form);
        }
    });
})(window.jQuery);
