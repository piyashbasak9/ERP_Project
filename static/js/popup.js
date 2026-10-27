(function ($) {
    const useJqueryUi = $ && $.fn.dialog;
    let $frame = null;
    let nativeDialog = null;
    let nativeFrame = null;
    let $confirmDialog = null;
    let confirmTarget = null;

    function openNativePopup(link, title, width, height) {
        if (!nativeDialog) {
            nativeDialog = document.createElement('dialog');
            nativeDialog.className = 'app-popup-native-dialog';
            nativeDialog.innerHTML = '<header class="app-popup-header"><strong></strong><button type="button" aria-label="Close">&times;</button></header><iframe title="" class="app-popup-frame"></iframe>';
            document.body.appendChild(nativeDialog);
            nativeFrame = nativeDialog.querySelector('iframe');
            nativeDialog.querySelector('button').addEventListener('click', function () {
                nativeDialog.close();
                nativeFrame.src = 'about:blank';
            });
            nativeDialog.addEventListener('close', function () {
                nativeFrame.src = 'about:blank';
            });
        }

        nativeDialog.style.width = Math.min(width, window.innerWidth - 32) + 'px';
        nativeDialog.style.height = Math.min(height, window.innerHeight - 32) + 'px';
        nativeDialog.querySelector('strong').textContent = title;
        nativeFrame.title = title;
        nativeFrame.src = link.href;
        nativeDialog.showModal();
    }

    function handlePopupClick(event, link) {
        if (
            event.defaultPrevented ||
            (event.which && event.which !== 1) ||
            event.ctrlKey ||
            event.metaKey ||
            event.shiftKey ||
            event.altKey
        ) {
            return;
        }

        event.preventDefault();
        const title = link.getAttribute('data-popup-title') || link.textContent.trim() || 'Details';
        const width = Number(link.getAttribute('data-popup-width')) || 900;
        const height = Number(link.getAttribute('data-popup-height')) || 760;

        if (!useJqueryUi) {
            openNativePopup(link, title, width, height);
            return;
        }

        const $dialog = $('.app-popup-dialog');
        $dialog.dialog('option', {
            title: title,
            width: Math.min(width, window.innerWidth - 32),
            height: Math.min(height, window.innerHeight - 32)
        });

        $frame = $('<iframe>', {
            src: link.href,
            title: title,
            css: {
                width: '100%',
                height: '100%',
                minHeight: '300px',
                border: 0
            }
        }).appendTo($dialog.empty());

        $dialog.dialog('open');
    }

    function handlePopupMessage(event) {
        if (
            event.origin !== window.location.origin ||
            (event.data !== 'erp-popup-complete' && event.data !== 'erp-popup-close')
        ) {
            return;
        }

        const sourceFrame = useJqueryUi && $frame
            ? $frame[0]
            : nativeFrame;
        if (!sourceFrame || event.source !== sourceFrame.contentWindow) {
            return;
        }

        if (useJqueryUi && $frame) {
            $frame.closest('.app-popup-dialog').dialog('close');
        } else if (nativeDialog) {
            nativeDialog.close();
        }

        if (event.data === 'erp-popup-complete') {
            window.location.reload();
        }
    }

    function sendDeleteRequest(link) {
        const csrfInput = document.querySelector('[name=csrfmiddlewaretoken]');
        const csrfToken = csrfInput ? csrfInput.value : '';
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
                'X-CSRFToken': csrfToken,
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
            window.alert(error.message);
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

    if (useJqueryUi) {
        $(function () {
            const $dialog = $('<div class="app-popup-dialog"></div>').appendTo('body');
            $dialog.dialog({
                autoOpen: false,
                modal: true,
                resizable: true,
                dialogClass: 'app-popup-window',
                width: Math.min(900, window.innerWidth - 32),
                height: Math.min(760, window.innerHeight - 32),
                close: function () {
                    if ($frame) {
                        $frame.attr('src', 'about:blank').remove();
                        $frame = null;
                    }
                }
            });
        });
    }

    document.addEventListener('click', function (event) {
        const target = event.target instanceof Element ? event.target : null;
        if (!target) {
            return;
        }

        const closeControl = target.closest('[data-popup-close]');
        if (closeControl && window.parent !== window) {
            event.preventDefault();
            window.parent.postMessage('erp-popup-close', window.location.origin);
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
            handlePopupClick(event, link);
        }
    });

    window.addEventListener('message', handlePopupMessage);
})(window.jQuery);
