/**
 * Handle attempt form behavior, specifically LinkedIn outcome dropdown
 */
(function() {
  'use strict';

  function initAttemptForm() {
    const channelSelect = document.querySelector('form[action*="/attempts/create"] select[name="channel"]');
    const outcomeTextInput = document.getElementById('outcome-text-input');
    const outcomeDropdown = document.getElementById('outcome-dropdown');
    const outcomeOtherInput = document.getElementById('outcome-other-input');

    if (!channelSelect || !outcomeTextInput || !outcomeDropdown || !outcomeOtherInput) {
      // Form not present on this page
      return;
    }

    function toggleOutcomeFields() {
      const selectedChannel = channelSelect.value;
      const isLinkedIn = selectedChannel === 'linkedin';

      if (isLinkedIn) {
        // Show dropdown, hide text input
        outcomeTextInput.style.display = 'none';
        outcomeTextInput.removeAttribute('name'); // Remove name so it's not submitted
        outcomeDropdown.style.display = 'block';
        outcomeDropdown.setAttribute('name', 'outcome'); // Set name for submission
        outcomeOtherInput.style.display = 'none';
        outcomeOtherInput.removeAttribute('name');
        // Clear values
        outcomeTextInput.value = '';
        outcomeOtherInput.value = '';
      } else {
        // Show text input, hide dropdown
        outcomeTextInput.style.display = 'block';
        outcomeTextInput.setAttribute('name', 'outcome'); // Set name for submission
        outcomeDropdown.style.display = 'none';
        outcomeDropdown.removeAttribute('name'); // Remove name so it's not submitted
        outcomeOtherInput.style.display = 'none';
        outcomeOtherInput.removeAttribute('name');
        // Clear values
        outcomeDropdown.value = '';
        outcomeOtherInput.value = '';
      }
    }

    function handleOutcomeDropdownChange() {
      const selectedValue = outcomeDropdown.value;
      if (selectedValue === 'Other') {
        // Show custom input for "Other"
        outcomeOtherInput.style.display = 'block';
        outcomeOtherInput.setAttribute('name', 'outcome'); // Set name for submission
        outcomeDropdown.removeAttribute('name'); // Remove name from dropdown
        outcomeOtherInput.value = '';
        outcomeOtherInput.focus();
      } else {
        // Hide custom input
        outcomeOtherInput.style.display = 'none';
        outcomeOtherInput.removeAttribute('name');
        outcomeDropdown.setAttribute('name', 'outcome'); // Set name back to dropdown
        outcomeOtherInput.value = '';
      }
    }

    // Initial state - check if LinkedIn is already selected
    toggleOutcomeFields();
    
    // Also handle initial "Other" selection if dropdown is already set
    if (outcomeDropdown.style.display !== 'none' && outcomeDropdown.value === 'Other') {
      handleOutcomeDropdownChange();
    }

    // Listen for channel changes
    channelSelect.addEventListener('change', toggleOutcomeFields);

    // Listen for outcome dropdown changes
    outcomeDropdown.addEventListener('change', handleOutcomeDropdownChange);

    // Handle form submission - validate LinkedIn outcomes
    const form = channelSelect.closest('form');
    if (form) {
      form.addEventListener('submit', function(e) {
        const selectedChannel = channelSelect.value;
        const isLinkedIn = selectedChannel === 'linkedin';

        if (isLinkedIn) {
          // For LinkedIn, validate that an outcome is selected
          if (outcomeDropdown.value === 'Other') {
            // Validate "other" input has a value
            if (!outcomeOtherInput.value.trim()) {
              e.preventDefault();
              alert('Please specify an outcome.');
              return false;
            }
          } else {
            // Validate dropdown has a selection
            if (!outcomeDropdown.value) {
              e.preventDefault();
              alert('Please select an outcome.');
              return false;
            }
          }
        }
        // For non-LinkedIn, no validation needed (optional field)
      });
    }
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAttemptForm);
  } else {
    initAttemptForm();
  }
})();
