(function () {
  'use strict';

  function getActiveProfileKey(profileChip) {
    if (profileChip) {
      const profileText = profileChip.textContent.trim().toLowerCase();
      return profileText === 'fisseha' ? 'fisseha' : 'abby';
    }
    return 'abby';
  }

  function updateProfileLabel(profileLabel, profileChip) {
    if (profileChip && profileLabel) {
      profileLabel.textContent = profileChip.textContent.trim();
    }
  }

  window.LinkedInTemplates = window.LinkedInTemplates || {};
  window.LinkedInTemplates.helpers = {
    getActiveProfileKey,
    updateProfileLabel,
  };
})();
