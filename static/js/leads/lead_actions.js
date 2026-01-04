(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', () => {
    const deleteButton = document.getElementById('delete-lead-button');
    const modal = document.getElementById('delete-lead-modal');
    const closeButtons = modal ? modal.querySelectorAll('[data-close-delete]') : [];
    const confirmButton = document.getElementById('confirm-delete-lead');
    const deleteForm = document.getElementById('delete-lead-form');

    function openModal() {
      if (modal) {
        modal.style.display = 'flex';
      }
    }

    function closeModal() {
      if (modal) {
        modal.style.display = 'none';
      }
    }

    deleteButton?.addEventListener('click', openModal);

    closeButtons.forEach((btn) => {
      btn.addEventListener('click', closeModal);
    });

    modal?.addEventListener('click', (event) => {
      if (event.target === modal) {
        closeModal();
      }
    });

    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        closeModal();
      }
    });

    confirmButton?.addEventListener('click', () => {
      if (deleteForm) {
        deleteForm.submit();
      }
    });

    const collapseButtons = document.querySelectorAll('[data-collapse-toggle]');
    collapseButtons.forEach((button) => {
      const targetSelector = button.getAttribute('data-target');
      if (!targetSelector) {
        return;
      }

      const panel = document.querySelector(targetSelector);
      if (!panel) {
        return;
      }

      const openLabel = button.dataset.openLabel || 'Hide';
      const closedLabel = button.dataset.closedLabel || 'Show';

      if (!panel.hasAttribute('data-collapsed')) {
        panel.dataset.collapsed = 'true';
      }

      function setState(collapsed) {
        panel.dataset.collapsed = collapsed ? 'true' : 'false';
        panel.hidden = collapsed;
        button.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        button.textContent = collapsed ? closedLabel : openLabel;
      }

      button.addEventListener('click', () => {
        const currentlyCollapsed = panel.dataset.collapsed !== 'false';
        setState(!currentlyCollapsed);
      });

      const initialCollapsed = panel.dataset.collapsed !== 'false';
      setState(initialCollapsed);
    });
  });
})();

