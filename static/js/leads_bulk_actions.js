/**
 * Bulk actions for leads list
 * Handles selection, action bar, and bulk operations
 */

(function() {
  'use strict';

  // State
  const selectedLeadIds = new Set();
  let pendingAction = null;
  let pendingActionData = null;

  // DOM elements
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

  // Initialize
  function init() {
    if (!selectAllCheckbox) return; // Not on leads page

    // Event listeners
    selectAllCheckbox.addEventListener('change', handleSelectAll);
    leadCheckboxes.forEach(cb => {
      cb.addEventListener('change', handleLeadCheckboxChange);
    });
    bulkStatusSelect.addEventListener('change', handleStatusChange);
    bulkMarkMailSentBtn.addEventListener('click', handleMarkMailSent);
    bulkClearSelectionBtn.addEventListener('click', clearSelection);
    confirmOkBtn.addEventListener('click', executePendingAction);
    confirmCancelBtn.addEventListener('click', closeConfirmModal);

    // Close modal on backdrop click
    confirmModal.addEventListener('click', (e) => {
      if (e.target === confirmModal) {
        closeConfirmModal();
      }
    });

    updateUI();
  }

  // Handle select all checkbox
  function handleSelectAll(e) {
    const checked = e.target.checked;
    leadCheckboxes.forEach(cb => {
      if (!cb.disabled) {
        cb.checked = checked;
        if (checked) {
          selectedLeadIds.add(parseInt(cb.dataset.leadId));
        } else {
          selectedLeadIds.delete(parseInt(cb.dataset.leadId));
        }
      }
    });
    updateUI();
  }

  // Handle individual lead checkbox
  function handleLeadCheckboxChange(e) {
    const leadId = parseInt(e.target.dataset.leadId);
    if (e.target.checked) {
      selectedLeadIds.add(leadId);
    } else {
      selectedLeadIds.delete(leadId);
    }
    updateSelectAllState();
    updateUI();
  }

  // Update select all checkbox state
  function updateSelectAllState() {
    const enabledCheckboxes = Array.from(leadCheckboxes).filter(cb => !cb.disabled);
    const checkedCount = Array.from(enabledCheckboxes).filter(cb => cb.checked).length;
    selectAllCheckbox.checked = checkedCount > 0 && checkedCount === enabledCheckboxes.length;
    selectAllCheckbox.indeterminate = checkedCount > 0 && checkedCount < enabledCheckboxes.length;
  }

  // Update UI based on selection
  function updateUI() {
    const count = selectedLeadIds.size;
    bulkSelectionCount.textContent = count;
    
    if (count > 0) {
      bulkActionsBar.style.display = 'flex';
    } else {
      bulkActionsBar.style.display = 'none';
      bulkStatusSelect.value = '';
    }
  }

  // Clear selection
  function clearSelection() {
    selectedLeadIds.clear();
    leadCheckboxes.forEach(cb => {
      cb.checked = false;
    });
    selectAllCheckbox.checked = false;
    selectAllCheckbox.indeterminate = false;
    updateUI();
  }

  // Handle status change
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

  // Handle mark mail sent
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

  // Show confirmation modal
  function showConfirmModal(title, message, action, data) {
    pendingAction = action;
    pendingActionData = data;
    confirmTitle.textContent = title;
    confirmMessage.innerHTML = message;
    confirmModal.style.display = 'flex';
  }

  // Close confirmation modal
  function closeConfirmModal() {
    confirmModal.style.display = 'none';
    pendingAction = null;
    pendingActionData = null;
    bulkStatusSelect.value = '';
  }

  // Execute pending action
  async function executePendingAction() {
    if (!pendingAction || selectedLeadIds.size === 0) {
      closeConfirmModal();
      return;
    }

    const leadIds = Array.from(selectedLeadIds);
    let endpoint, method, body;

    if (pendingAction === 'change-status') {
      endpoint = '/leads/bulk/change-status';
      method = 'POST';
      body = {
        lead_ids: leadIds,
        status: pendingActionData.status
      };
    } else if (pendingAction === 'mark-mail-sent') {
      endpoint = '/leads/bulk/mark-mail-sent';
      method = 'POST';
      body = {
        lead_ids: leadIds
      };
    } else {
      closeConfirmModal();
      return;
    }

    try {
      // Disable buttons during request
      confirmOkBtn.disabled = true;
      confirmOkBtn.textContent = 'Processing...';

      const response = await fetch(endpoint, {
        method: method,
        headers: {
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        },
        body: JSON.stringify(body)
      });

      const result = await response.json();

      if (!response.ok) {
        throw new Error(result.detail || 'Action failed');
      }

      // Show success message
      const message = buildSuccessMessage(pendingAction, result);
      if (typeof showSuccess === 'function') {
        showSuccess(message);
      } else {
        alert(message);
      }

      // Close modal and clear selection
      closeConfirmModal();
      clearSelection();

      // Reload page to reflect changes
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

  // Build success message
  function buildSuccessMessage(action, result) {
    if (action === 'change-status') {
      return `Successfully updated status for ${result.updated || 0} lead(s).`;
    } else if (action === 'mark-mail-sent') {
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

  // Initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

