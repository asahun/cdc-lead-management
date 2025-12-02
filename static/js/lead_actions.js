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
  });
})();

