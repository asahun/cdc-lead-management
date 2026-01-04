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

  // All channels (including LinkedIn) now use free text input
  // No special handling needed - just ensure text input is always visible
  if (outcomeTextInput) {
    outcomeTextInput.style.display = 'block';
    outcomeTextInput.setAttribute('name', 'outcome');
  }
  if (outcomeDropdown) {
    outcomeDropdown.style.display = 'none';
    outcomeDropdown.removeAttribute('name');
  }
  if (outcomeOtherInput) {
    outcomeOtherInput.style.display = 'none';
    outcomeOtherInput.removeAttribute('name');
  }
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAttemptForm);
  } else {
    initAttemptForm();
  }
})();
