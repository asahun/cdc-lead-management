(function () {
  'use strict';

  function updateSelectionUi(elements, count) {
    if (!elements) return;
    const { bulkSelectionCount, bulkActionsBar, bulkStatusSelect } = elements;
    if (bulkSelectionCount) {
      bulkSelectionCount.textContent = count;
    }
    if (bulkActionsBar) {
      bulkActionsBar.style.display = count > 0 ? 'flex' : 'none';
    }
    if (count === 0 && bulkStatusSelect) {
      bulkStatusSelect.value = '';
    }
  }

  function updateSelectAllState(selectAllCheckbox, leadCheckboxes) {
    if (!selectAllCheckbox) return;
    const enabledCheckboxes = Array.from(leadCheckboxes).filter((cb) => !cb.disabled);
    const checkedCount = enabledCheckboxes.filter((cb) => cb.checked).length;
    selectAllCheckbox.checked =
      checkedCount > 0 && checkedCount === enabledCheckboxes.length;
    selectAllCheckbox.indeterminate =
      checkedCount > 0 && checkedCount < enabledCheckboxes.length;
  }

  function showConfirmModal(modalEls, title, message) {
    const { confirmModal, confirmTitle, confirmMessage } = modalEls;
    if (!confirmModal) return;
    if (confirmTitle) confirmTitle.textContent = title;
    if (confirmMessage) confirmMessage.innerHTML = message;
    confirmModal.style.display = 'flex';
  }

  function closeConfirmModal(modalEls) {
    const { confirmModal } = modalEls;
    if (!confirmModal) return;
    confirmModal.style.display = 'none';
  }

  function buildSuccessMessage(action, result) {
    if (action === 'change-status') {
      return `Successfully updated status for ${result.updated || 0} lead(s).`;
    }
    if (action === 'mark-mail-sent') {
      const parts = [];
      if (result.leads_processed) {
        parts.push(`${result.leads_processed} lead(s) processed`);
      }
      if (result.print_logs_marked) {
        parts.push(`${result.print_logs_marked} print log(s) marked as mailed`);
      }
      if (result.attempts_created) {
        parts.push(`${result.attempts_created} attempt(s) created`);
      }
      return `Successfully completed bulk action. ${parts.join(', ')}.`;
    }
    return 'Action completed successfully.';
  }

  window.LeadsBulk = window.LeadsBulk || {};
  window.LeadsBulk.render = {
    updateSelectionUi,
    updateSelectAllState,
    showConfirmModal,
    closeConfirmModal,
    buildSuccessMessage,
  };
})();
