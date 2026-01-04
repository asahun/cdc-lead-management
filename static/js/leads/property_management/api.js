(function () {
  'use strict';

  const api = {
    async fetchRelatedProperties(leadId, flip) {
      const flipParam = flip ? '?flip=true' : '';
      const response = await fetch(`/leads/${leadId}/properties/related${flipParam}`);
      if (!response.ok) {
        throw new Error('Error loading properties. Please try again.');
      }
      return response.json();
    },
  };

  window.PropertyManagement = window.PropertyManagement || {};
  window.PropertyManagement.api = api;
})();
