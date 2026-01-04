(function () {
  'use strict';

  const api = window.LeadsBulk?.api;
  const render = window.LeadsBulk?.render;
  if (!api || !render) return;

  const selectedLeadIds = new Set();
  let pendingAction = null;
  let pendingActionData = null;

  const selectAllCheckbox = document.getElementById('select-all-leads');
  const leadCheckboxes = document.querySelectorAll('.lead-checkbox');
  const bulkActionsBar = document.getElementById('bulk-actions-bar');
  const bulkSelectionCount = document.getElementById('bulk-selection-count');
  const bulkStatusSelect = document.getElementById('bulk-status-select');
  const bulkMarkMailSentBtn = document.getElementById('bulk-mark-mail-sent');
  const bulkClearSelectionBtn = document.getElementById('bulk-clear-selection');
  const confirmModal = document.getElementById('bulk-confirm-modal');
  const confirmTitle = document.getElementById('bulk-confirm-title');
  const confirmMessage = document.getElementById('bulk-confirm-message');
  const confirmOkBtn = document.getElementById('bulk-confirm-ok');
  const confirmCancelBtn = document.getElementById('bulk-confirm-cancel');

  const uiElements = {
    bulkSelectionCount,
    bulkActionsBar,
    bulkStatusSelect,
  };
  const modalEls = {
    confirmModal,
    confirmTitle,
    confirmMessage,
  };

  function updateUI() {
    render.updateSelectionUi(uiElements, selectedLeadIds.size);
  }

  function handleSelectAll(e) {
    const checked = e.target.checked;
    leadCheckboxes.forEach((cb) => {
      if (!cb.disabled) {
        cb.checked = checked;
        const leadId = parseInt(cb.dataset.leadId, 10);
        if (checked) {
          selectedLeadIds.add(leadId);
        } else {
          selectedLeadIds.delete(leadId);
        }
      }
    });
    updateUI();
  }

  function handleLeadCheckboxChange(e) {
    const leadId = parseInt(e.target.dataset.leadId, 10);
    if (e.target.checked) {
      selectedLeadIds.add(leadId);
    } else {
      selectedLeadIds.delete(leadId);
    }
    render.updateSelectAllState(selectAllCheckbox, leadCheckboxes);
    updateUI();
  }

  function clearSelection() {
    selectedLeadIds.clear();
    leadCheckboxes.forEach((cb) => {
      cb.checked = false;
    });
    selectAllCheckbox.checked = false;
    selectAllCheckbox.indeterminate = false;
    updateUI();
  }

  function showConfirmModal(title, message, action, data) {
    pendingAction = action;
    pendingActionData = data;
    render.showConfirmModal(modalEls, title, message);
  }

  function closeConfirmModal() {
    render.closeConfirmModal(modalEls);
    pendingAction = null;
    pendingActionData = null;
    bulkStatusSelect.value = '';
  }

  function handleStatusChange(e) {
    const newStatus = e.target.value;
    if (!newStatus) return;

    const count = selectedLeadIds.size;
    if (count === 0) {
      e.target.value = '';
      return;
    }

    showConfirmModal(
      'Change Status',
      `Are you sure you want to change the status to <strong>${newStatus}</strong> for <strong>${count}</strong> lead(s)?`,
      'change-status',
      { status: newStatus }
    );
  }

  function handleMarkMailSent() {
    const count = selectedLeadIds.size;
    if (count === 0) return;

    showConfirmModal(
      'Mark Mail Sent',
      `Are you sure you want to mark all unmailed print logs as mailed for <strong>${count}</strong> lead(s)?<br><br>This will create attempt records for each mailed print log.`,
      'mark-mail-sent',
      {}
    );
  }

  async function executePendingAction() {
    if (!pendingAction || selectedLeadIds.size === 0) {
      closeConfirmModal();
      return;
    }

    const leadIds = Array.from(selectedLeadIds);

    try {
      confirmOkBtn.disabled = true;
      confirmOkBtn.textContent = 'Processing...';

      let result;
      if (pendingAction === 'change-status') {
        result = await api.changeStatus(leadIds, pendingActionData.status);
      } else if (pendingAction === 'mark-mail-sent') {
        result = await api.markMailSent(leadIds);
      } else {
        closeConfirmModal();
        return;
      }

      const message = render.buildSuccessMessage(pendingAction, result);
      if (typeof showSuccess === 'function') {
        showSuccess(message);
      } else {
        alert(message);
      }

      closeConfirmModal();
      clearSelection();
      window.location.reload();
    } catch (error) {
      if (typeof showError === 'function') {
        showError(error.message || 'Failed to perform bulk action');
      } else {
        alert('Error: ' + (error.message || 'Failed to perform bulk action'));
      }
    } finally {
      confirmOkBtn.disabled = false;
      confirmOkBtn.textContent = 'Confirm';
    }
  }

  function init() {
    if (!selectAllCheckbox) return;

    selectAllCheckbox.addEventListener('change', handleSelectAll);
    leadCheckboxes.forEach((cb) => {
      cb.addEventListener('change', handleLeadCheckboxChange);
    });
    bulkStatusSelect.addEventListener('change', handleStatusChange);
    bulkMarkMailSentBtn.addEventListener('click', handleMarkMailSent);
    bulkClearSelectionBtn.addEventListener('click', clearSelection);
    confirmOkBtn.addEventListener('click', executePendingAction);
    confirmCancelBtn.addEventListener('click', closeConfirmModal);

    confirmModal.addEventListener('click', (e) => {
      if (e.target === confirmModal) {
        closeConfirmModal();
      }
    });

    updateUI();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
