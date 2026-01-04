(function () {
  'use strict';

  const api = {
    async fetchJourney(leadId) {
      const res = await fetch(`/api/leads/${leadId}/journey`);
      if (!res.ok) {
        throw new Error('Failed to load journey data');
      }
      return res.json();
    },
  };

  window.JourneyDisplay = window.JourneyDisplay || {};
  window.JourneyDisplay.api = api;
})();
