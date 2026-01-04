(function () {
  'use strict';

  const helpers = window.LetterPrint?.helpers;
  if (!helpers) return;

  function setEmptyState(listEl) {
    if (!listEl) return;
    listEl.innerHTML = '<p class="empty-state">Letters you print will appear here.</p>';
  }

  function renderPrintLogs(listEl, logs, handlers) {
    if (!listEl) return;
    if (!logs.length) {
      setEmptyState(listEl);
      return;
    }

    listEl.innerHTML = '';
    logs.forEach((log) => {
      const item = document.createElement('article');
      item.className = 'print-log-item';
      item.dataset.logId = log.id;

      const head = document.createElement('div');
      head.className = 'print-log-head';

      const contactBlock = document.createElement('div');
      contactBlock.className = 'print-log-contact';
      const nameLine = document.createElement('p');
      nameLine.textContent = log.contactName || 'Unknown contact';
      if (log.contactTitle) {
        const title = document.createElement('span');
        title.className = 'print-log-title';
        title.textContent = log.contactTitle;
        nameLine.appendChild(document.createTextNode(' '));
        nameLine.appendChild(title);
      }
      contactBlock.appendChild(nameLine);

      const addressText = (log.addressLines || []).filter(Boolean).join(', ');
      if (addressText) {
        const address = document.createElement('span');
        address.className = 'print-log-address';
        address.textContent = addressText;
        contactBlock.appendChild(address);
      }

      head.appendChild(contactBlock);

      const meta = document.createElement('div');
      meta.className = 'print-log-meta';
      const printed = document.createElement('span');
      printed.className = 'print-log-time';
      printed.textContent = helpers.formatLocalTime(log.printedAt);
      meta.appendChild(printed);

      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.className = 'print-log-delete';
      deleteBtn.dataset.logId = log.id;
      deleteBtn.setAttribute('aria-label', 'Delete print log');
      deleteBtn.textContent = '🗑';
      deleteBtn.addEventListener('click', () => handlers.onDelete(log));
      meta.appendChild(deleteBtn);

      head.appendChild(meta);
      item.appendChild(head);

      const pathLine = document.createElement('code');
      pathLine.className = 'print-log-path';
      pathLine.textContent = log.filePath || log.filename || 'Unknown location';
      item.appendChild(pathLine);

      const controls = document.createElement('div');
      controls.className = 'print-log-controls';
      const label = document.createElement('label');
      label.className = 'print-log-mail-control';
      if (log.mailed) {
        label.classList.add('mailed');
      }
      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.className = 'print-log-mail-toggle';
      checkbox.dataset.logId = log.id;
      checkbox.checked = Boolean(log.mailed);
      checkbox.disabled = log.mailed;
      checkbox.addEventListener('change', (event) => handlers.onToggleMail(event, log.id));
      label.appendChild(checkbox);
      const labelText = document.createElement('span');
      labelText.textContent = log.mailed ? 'Mailed' : 'Mark as mailed';
      label.appendChild(labelText);
      controls.appendChild(label);
      item.appendChild(controls);

      listEl.appendChild(item);
    });
  }

  function setButtonState(button, state) {
    const defaultLabel = button.dataset.defaultLabel || 'Generate Letter';
    if (state === 'loading') {
      button.disabled = true;
      button.classList.add('loading');
      button.classList.remove('success');
      button.textContent = 'Generating…';
      return;
    }
    if (state === 'success') {
      button.disabled = true;
      button.classList.remove('loading');
      button.classList.add('success');
      button.textContent = 'Saved!';
      setTimeout(() => setButtonState(button, 'idle'), 2200);
      return;
    }
    button.disabled = false;
    button.classList.remove('loading', 'success');
    button.textContent = defaultLabel;
  }

  window.LetterPrint = window.LetterPrint || {};
  window.LetterPrint.render = {
    setEmptyState,
    renderPrintLogs,
    setButtonState,
  };
})();
