(function () {
  'use strict';

  const api = window.LetterPrint?.api;
  const helpers = window.LetterPrint?.helpers;
  const render = window.LetterPrint?.render;
  if (!api || !helpers || !render) return;

  const letterButtons = Array.from(document.querySelectorAll('.generate-letter-btn'));
  const printLogSection = document.getElementById('print-log');
  const printLogList = document.getElementById('print-log-list');
  const leadId = printLogSection ? printLogSection.dataset.leadId : null;
  const deleteModal = document.getElementById('delete-print-log-modal');
  const deleteMessage = document.getElementById('delete-print-log-message');
  const deleteConfirmBtn = document.getElementById('confirm-delete-print-log');
  const deleteCloseButtons = deleteModal
    ? deleteModal.querySelectorAll('[data-close-print-log]')
    : [];

  let pendingDeleteLogId = null;
  let printLogsCache = [];

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

  async function refreshPrintLogs() {
    if (!leadId || !printLogSection) {
      return;
    }

    try {
      const payload = await api.fetchPrintLogs(leadId);
      printLogsCache = Array.isArray(payload.logs) ? payload.logs : [];
      render.renderPrintLogs(printLogList, printLogsCache, {
        onDelete: openDeleteModal,
        onToggleMail: handleMailToggle,
      });
    } catch (error) {
      console.error(error);
    }
  }

  async function handleMailToggle(event, logId) {
    const current = event.currentTarget;
    if (!current.checked) {
      return;
    }
    current.disabled = true;
    if (!logId) {
      current.disabled = false;
      current.checked = false;
      return;
    }

    try {
      await api.markPrintLogMailed(leadId, logId);
      const localLog = printLogsCache.find((entry) => String(entry.id) === String(logId));
      if (localLog) {
        localLog.mailed = true;
        localLog.mailedAt = new Date().toISOString();
      }
      render.renderPrintLogs(printLogList, printLogsCache, {
        onDelete: openDeleteModal,
        onToggleMail: handleMailToggle,
      });
      await refreshPrintLogs();
      await refreshAttempts();
    } catch (error) {
      current.checked = false;
      current.disabled = false;
      showError(error.message || 'Failed to mark letter as mailed.');
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
      const html = await api.refreshAttempts(leadId);
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

  async function deletePrintLog() {
    if (!leadId || !pendingDeleteLogId) {
      return;
    }

    try {
      await api.deletePrintLog(leadId, pendingDeleteLogId);
      closeDeleteModal();
      printLogsCache = printLogsCache.filter(
        (entry) => String(entry.id) !== String(pendingDeleteLogId)
      );
      render.renderPrintLogs(printLogList, printLogsCache, {
        onDelete: openDeleteModal,
        onToggleMail: handleMailToggle,
      });
      await refreshPrintLogs();
      await refreshAttempts();
    } catch (error) {
      showError(error.message || 'Failed to delete print log.');
    }
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

    render.setButtonState(button, 'loading');

    try {
      const { blob, disposition } = await api.generateLetter(url);
      const contactName = (button.dataset.contactName || '').trim();
      const contactSlug = helpers.buildContactSlug(contactName);
      const fallbackName = `${contactSlug}.pdf`;
      const filename = helpers.parseFilenameFromDisposition(disposition) || fallbackName;

      helpers.triggerDownload(blob, filename);
      render.setButtonState(button, 'success');
      await refreshPrintLogs();
    } catch (error) {
      render.setButtonState(button, 'idle');
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
      render.renderPrintLogs(printLogList, printLogsCache, {
        onDelete: openDeleteModal,
        onToggleMail: handleMailToggle,
      });
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
