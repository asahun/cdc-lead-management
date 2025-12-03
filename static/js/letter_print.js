(function () {
  'use strict';

  const letterButtons = Array.from(document.querySelectorAll('.generate-letter-btn'));
  const printLogSection = document.getElementById('print-log');
  const printLogList = document.getElementById('print-log-list');
  const leadId = printLogSection ? printLogSection.dataset.leadId : null;
  const deleteModal = document.getElementById('delete-print-log-modal');
  const deleteMessage = document.getElementById('delete-print-log-message');
  const deleteConfirmBtn = document.getElementById('confirm-delete-print-log');
  const deleteCloseButtons = deleteModal ? deleteModal.querySelectorAll('[data-close-print-log]') : [];

  let pendingDeleteLogId = null;
  let printLogsCache = [];

  function formatLocalTime(iso) {
    if (!iso) return '';
    const parsed = new Date(iso);
    if (Number.isNaN(parsed.getTime())) {
      return iso;
    }
    return parsed.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function setEmptyState() {
    if (!printLogList) return;
    printLogList.innerHTML = '<p class="empty-state">Letters you print will appear here.</p>';
  }

  function renderPrintLogs(logs) {
    if (!printLogList) {
      return;
    }

    if (!logs.length) {
      setEmptyState();
      return;
    }

    printLogList.innerHTML = '';
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
      printed.textContent = formatLocalTime(log.printedAt);
      meta.appendChild(printed);

      const deleteBtn = document.createElement('button');
      deleteBtn.type = 'button';
      deleteBtn.className = 'print-log-delete';
      deleteBtn.dataset.logId = log.id;
      deleteBtn.setAttribute('aria-label', 'Delete print log');
      deleteBtn.textContent = '🗑';
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
      label.appendChild(checkbox);
      const labelText = document.createElement('span');
      labelText.textContent = log.mailed ? 'Mailed' : 'Mark as mailed';
      label.appendChild(labelText);
      controls.appendChild(label);
      item.appendChild(controls);

      printLogList.appendChild(item);
    });

    attachMailHandlers();
    attachDeleteHandlers();
  }

  async function refreshPrintLogs() {
    if (!leadId || !printLogSection) {
      return;
    }

    try {
      const response = await fetch(`/leads/${leadId}/print-logs`, {
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        throw new Error('Failed to refresh print log');
      }
      const payload = await response.json();
      printLogsCache = Array.isArray(payload.logs) ? payload.logs : [];
      renderPrintLogs(printLogsCache);
    } catch (error) {
      console.error(error);
    }
  }

  async function markLogAsMailed(logId, checkbox) {
    if (!leadId) {
      return;
    }

    try {
      const response = await fetch(`/leads/${leadId}/print-logs/${logId}/mark-mailed`, {
        method: 'POST',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || 'Failed to mark as mailed');
      }
      const localLog = printLogsCache.find((entry) => String(entry.id) === String(logId));
      if (localLog) {
        localLog.mailed = true;
        localLog.mailedAt = new Date().toISOString();
      }
      renderPrintLogs(printLogsCache);
      await refreshPrintLogs();
      await refreshAttempts();
    } catch (error) {
      if (checkbox) {
        checkbox.checked = false;
        checkbox.disabled = false;
      }
      showError(error.message || 'Failed to mark letter as mailed.');
    }
  }

  function attachMailHandlers() {
    if (!printLogList) {
      return;
    }
    printLogList.querySelectorAll('.print-log-mail-toggle').forEach((checkbox) => {
      checkbox.addEventListener('change', (event) => {
        const current = event.currentTarget;
        if (!current.checked) {
          return;
        }
        current.disabled = true;
        const logId = current.dataset.logId;
        if (!logId) {
          current.disabled = false;
          current.checked = false;
          return;
        }
        markLogAsMailed(logId, current);
      });
    });
  }

  function attachDeleteHandlers() {
    if (!printLogList) {
      return;
    }
    printLogList.querySelectorAll('.print-log-delete').forEach((button) => {
      button.addEventListener('click', (event) => {
        const logId = event.currentTarget.dataset.logId;
        const log = printLogsCache.find((entry) => String(entry.id) === String(logId));
        if (log) {
          openDeleteModal(log);
        }
      });
    });
  }

  function openDeleteModal(log) {
    if (!deleteModal) return;
    pendingDeleteLogId = log.id;
    if (deleteMessage) {
      const description = log.filePath || log.filename || 'this entry';
      deleteMessage.textContent = `Delete the log for ${description}?`;
    }
    deleteModal.style.display = 'flex';
  }

  function closeDeleteModal() {
    if (!deleteModal) return;
    deleteModal.style.display = 'none';
    pendingDeleteLogId = null;
  }

  async function deletePrintLog() {
    if (!leadId || !pendingDeleteLogId) {
      return;
    }

    try {
      const response = await fetch(`/leads/${leadId}/print-logs/${pendingDeleteLogId}`, {
        method: 'DELETE',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || 'Failed to delete print log');
      }
      closeDeleteModal();
      printLogsCache = printLogsCache.filter(
        (entry) => String(entry.id) !== String(pendingDeleteLogId)
      );
      renderPrintLogs(printLogsCache);
      await refreshPrintLogs();
      await refreshAttempts();
    } catch (error) {
      showError(error.message || 'Failed to delete print log.');
    }
  }

  function initCollapseButton(button) {
    if (!button) return;
    const targetSelector = button.getAttribute('data-target');
    if (!targetSelector) return;
    const panel = document.querySelector(targetSelector);
    if (!panel) return;

    const openLabel = button.dataset.openLabel || 'Hide';
    const closedLabel = button.dataset.closedLabel || 'Show';

    if (!panel.hasAttribute('data-collapsed')) {
      panel.dataset.collapsed = 'true';
    }

    const setState = (collapsed) => {
      panel.dataset.collapsed = collapsed ? 'true' : 'false';
      panel.hidden = collapsed;
      button.setAttribute('aria-expanded', String(!collapsed));
      button.textContent = collapsed ? closedLabel : openLabel;
    };

    button.addEventListener('click', () => {
      const currentlyCollapsed = panel.dataset.collapsed !== 'false';
      setState(!currentlyCollapsed);
    });

    setState(panel.dataset.collapsed !== 'false');
  }

  async function refreshAttempts() {
    const attemptsContainer = document.getElementById('attempts');
    if (!attemptsContainer || !leadId) {
      return;
    }

    try {
      const response = await fetch(`/leads/${leadId}/edit`);
      if (!response.ok) {
        throw new Error('Failed to refresh attempts');
      }
      const html = await response.text();
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, 'text/html');
      const latestAttempts = doc.getElementById('attempts');
      if (latestAttempts) {
        attemptsContainer.replaceWith(latestAttempts);
        latestAttempts.querySelectorAll('[data-collapse-toggle]').forEach((btn) => {
          initCollapseButton(btn);
        });
      }
    } catch (error) {
      console.error(error);
    }
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

  function parseFilenameFromDisposition(headerValue) {
    if (!headerValue) {
      return '';
    }
    const utfMatch = headerValue.match(/filename\*=UTF-8''([^;]+)/i);
    if (utfMatch && utfMatch[1]) {
      return decodeURIComponent(utfMatch[1]);
    }
    const asciiMatch = headerValue.match(/filename="?([^";]+)"?/i);
    return asciiMatch && asciiMatch[1] ? asciiMatch[1] : '';
  }

  function triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename || 'letter.pdf';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  async function handleLetterClick(event) {
    const button = event.currentTarget;
    const url = button.dataset.letterUrl;
    if (!url) {
      return;
    }

    if (button.dataset.hasAddress === 'false') {
      showWarning('Add a mailing address to this contact before generating a letter.');
      return;
    }

    setButtonState(button, 'loading');

    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'X-Requested-With': 'fetch',
          Accept: 'application/pdf',
        },
      });
      if (!response.ok) {
        let message = 'Unable to generate letter.';
        try {
          const data = await response.json();
          if (data && data.detail) {
            message = data.detail;
          }
        } catch {
          const text = await response.text();
          if (text) {
            message = text;
          }
        }
        throw new Error(message);
      }

      const blob = await response.blob();
      const disposition = response.headers.get('Content-Disposition') || '';
      const contactName = (button.dataset.contactName || '').trim();
      const contactSlug = contactName
        ? contactName.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'letter'
        : 'letter';
      const fallbackName = `${contactSlug}.pdf`;
      const filename = parseFilenameFromDisposition(disposition) || fallbackName;

      triggerDownload(blob, filename);
      setButtonState(button, 'success');
      await refreshPrintLogs();
    } catch (error) {
      setButtonState(button, 'idle');
      showError(error.message || 'Unable to generate letter.');
    }
  }

  function init() {
    if (printLogSection) {
      try {
        const initial = JSON.parse(printLogSection.dataset.printLogs || '[]');
        if (Array.isArray(initial)) {
          printLogsCache = initial;
        }
      } catch {
        printLogsCache = [];
      }
      renderPrintLogs(printLogsCache);
    }

    letterButtons.forEach((button) => {
      if (!button.dataset.defaultLabel) {
        button.dataset.defaultLabel = button.textContent.trim();
      }
      button.addEventListener('click', handleLetterClick);
    });

    deleteCloseButtons.forEach((btn) => {
      btn.addEventListener('click', closeDeleteModal);
    });

    deleteModal?.addEventListener('click', (event) => {
      if (event.target === deleteModal) {
        closeDeleteModal();
      }
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        closeDeleteModal();
      }
    });

    deleteConfirmBtn?.addEventListener('click', deletePrintLog);
  }

  init();
})();
