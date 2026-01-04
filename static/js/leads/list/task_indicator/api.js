(function () {
  'use strict';

  const api = {
    async fetchJourneyStatuses(leadIds) {
      const response = await fetch('/api/leads/batch/journey-status', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ lead_ids: leadIds }),
      });
      if (!response.ok) {
        throw new Error('Failed to load journey statuses');
      }
      return response.json();
    },

    async fetchJourney(leadId) {
      const response = await fetch(`/api/leads/${leadId}/journey`);
      if (!response.ok) {
        throw new Error('Failed to load tasks');
      }
      return response.json();
    },
  };

  window.TaskIndicator = window.TaskIndicator || {};
  window.TaskIndicator.api = api;
})();
