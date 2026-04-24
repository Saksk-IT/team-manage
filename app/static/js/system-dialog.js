(function () {
    'use strict';

    let activeConfirm = Promise.resolve();
    let confirmId = 0;

    function normalizeOptions(options) {
        if (typeof options === 'string') {
            return { message: options };
        }
        return options && typeof options === 'object' ? options : {};
    }

    function createTextElement(tagName, className, text) {
        const element = document.createElement(tagName);
        element.className = className;
        element.textContent = text;
        return element;
    }

    function getFocusableElements(container) {
        return Array.from(container.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'))
            .filter(element => !element.disabled && element.offsetParent !== null);
    }

    function buildConfirmElements(config, titleId, descriptionId) {
        const overlay = document.createElement('div');
        overlay.className = 'system-confirm-overlay';
        overlay.setAttribute('role', 'presentation');

        const dialog = document.createElement('div');
        dialog.className = `system-confirm${config.danger ? ' system-confirm--danger' : ''}`;
        dialog.setAttribute('role', 'dialog');
        dialog.setAttribute('aria-modal', 'true');
        dialog.setAttribute('aria-labelledby', titleId);
        dialog.setAttribute('aria-describedby', descriptionId);

        const header = document.createElement('div');
        header.className = 'system-confirm__header';

        const icon = document.createElement('div');
        icon.className = 'system-confirm__icon';
        icon.innerHTML = '<i data-lucide="alert-triangle" aria-hidden="true"></i>';

        const title = createTextElement('h3', 'system-confirm__title', config.title);
        title.id = titleId;

        const message = createTextElement('p', 'system-confirm__message', config.message);
        message.id = descriptionId;

        const actions = document.createElement('div');
        actions.className = 'system-confirm__actions';

        const cancelButton = createTextElement('button', 'btn btn-secondary system-confirm__button', config.cancelText);
        cancelButton.type = 'button';

        const confirmButtonClass = config.danger ? 'btn btn-danger system-confirm__button' : 'btn btn-primary system-confirm__button';
        const confirmButton = createTextElement('button', confirmButtonClass, config.confirmText);
        confirmButton.type = 'button';

        header.append(icon, title);
        actions.append(cancelButton, confirmButton);
        dialog.append(header, message, actions);
        overlay.append(dialog);

        return { overlay, dialog, cancelButton, confirmButton };
    }

    function trapFocus(dialog, event) {
        const focusableElements = getFocusableElements(dialog);
        if (focusableElements.length === 0) {
            event.preventDefault();
            return;
        }

        const firstElement = focusableElements[0];
        const lastElement = focusableElements[focusableElements.length - 1];

        if (event.shiftKey && document.activeElement === firstElement) {
            event.preventDefault();
            lastElement.focus();
        } else if (!event.shiftKey && document.activeElement === lastElement) {
            event.preventDefault();
            firstElement.focus();
        }
    }

    function buildConfig(options) {
        return {
            title: '请确认操作',
            message: '',
            confirmText: '确认',
            cancelText: '取消',
            danger: false,
            ...normalizeOptions(options),
        };
    }

    function runConfirm(options) {
        const config = buildConfig(options);
        return new Promise(resolve => {
            const titleId = `systemConfirmTitle${++confirmId}`;
            const descriptionId = `systemConfirmMessage${confirmId}`;
            const previousActiveElement = document.activeElement;
            const previousOverflow = document.body.style.overflow;
            const { overlay, dialog, cancelButton, confirmButton } = buildConfirmElements(config, titleId, descriptionId);
            let settled = false;

            function closeDialog(result) {
                if (settled) return;
                settled = true;
                overlay.classList.remove('show');
                document.removeEventListener('keydown', handleKeydown);
                document.body.classList.remove('system-dialog-open');
                document.body.style.overflow = previousOverflow;

                window.setTimeout(() => {
                    overlay.remove();
                    previousActiveElement?.focus?.({ preventScroll: true });
                    resolve(result);
                }, 120);
            }

            function handleKeydown(event) {
                if (event.key === 'Escape') {
                    event.preventDefault();
                    closeDialog(false);
                } else if (event.key === 'Tab') {
                    trapFocus(dialog, event);
                }
            }

            cancelButton.addEventListener('click', () => closeDialog(false));
            confirmButton.addEventListener('click', () => closeDialog(true));
            overlay.addEventListener('click', event => {
                if (event.target === overlay) closeDialog(false);
            });
            document.addEventListener('keydown', handleKeydown);

            document.body.append(overlay);
            document.body.classList.add('system-dialog-open');
            document.body.style.overflow = 'hidden';

            window.requestAnimationFrame(() => overlay.classList.add('show'));
            window.lucide?.createIcons?.();
            (config.danger ? cancelButton : confirmButton).focus({ preventScroll: true });
        });
    }

    window.showSystemConfirm = function showSystemConfirm(options) {
        const queuedConfirm = activeConfirm.then(() => runConfirm(options), () => runConfirm(options));
        activeConfirm = queuedConfirm.catch(() => false);
        return queuedConfirm;
    };
})();
