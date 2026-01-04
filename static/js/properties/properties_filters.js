// properties_filters.js
// Handle filter interactions for properties page

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
      
      selects.forEach(select => {
        select.value = '';
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
})();

