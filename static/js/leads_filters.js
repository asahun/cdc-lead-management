// leads_filters.js
// Handle filter interactions and URL updates

(function() {
  'use strict';

  const filtersForm = document.getElementById('filters-form');
  const clearFiltersBtn = document.getElementById('clear-filters');
  const searchForm = document.querySelector('.page-actions form');

  if (!filtersForm) return;

  // Clear all filters
  if (clearFiltersBtn) {
    clearFiltersBtn.addEventListener('click', function(e) {
      e.preventDefault();
      
      // Reset all filter inputs
      const selects = filtersForm.querySelectorAll('select');
      const inputs = filtersForm.querySelectorAll('input[type="number"]');
      
      selects.forEach(select => {
        if (select.name === 'attempt_type') {
          select.value = 'all';
        } else if (select.name === 'print_log_mailed') {
          select.value = 'all';
        } else {
          select.value = '';
        }
      });
      
      inputs.forEach(input => {
        input.value = '';
      });

      // Submit form to apply cleared filters
      filtersForm.submit();
    });
  }

  // Sync search form with filter form
  if (searchForm && filtersForm) {
    searchForm.addEventListener('submit', function(e) {
      // Copy all filter values to search form hidden inputs
      const filterInputs = filtersForm.querySelectorAll('input, select');
      filterInputs.forEach(input => {
        if (input.name && input.name !== 'q' && input.name !== 'page') {
          let hiddenInput = searchForm.querySelector(`input[name="${input.name}"]`);
          if (!hiddenInput) {
            hiddenInput = document.createElement('input');
            hiddenInput.type = 'hidden';
            hiddenInput.name = input.name;
            searchForm.appendChild(hiddenInput);
          }
          hiddenInput.value = input.value;
        }
      });
    });
  }

  // Auto-submit on filter change (optional - can be removed if manual "Apply Filters" is preferred)
  // Uncomment if you want auto-submit behavior:
  /*
  const filterInputs = filtersForm.querySelectorAll('select, input[type="number"]');
  filterInputs.forEach(input => {
    input.addEventListener('change', function() {
      // Small delay to allow multiple rapid changes
      clearTimeout(window.filterTimeout);
      window.filterTimeout = setTimeout(() => {
        filtersForm.submit();
      }, 500);
    });
  });
  */
})();

