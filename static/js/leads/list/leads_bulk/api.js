(function () {
  'use strict';

  const api = {
    async changeStatus(leadIds, status) {
      const response = await fetch('/leads/bulk/change-status', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({ lead_ids: leadIds, status }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(result.detail || 'Action failed');
      }
      return result;
    },

    async markMailSent(leadIds) {
      const response = await fetch('/leads/bulk/mark-mail-sent', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Accept: 'application/json',
        },
        body: JSON.stringify({ lead_ids: leadIds }),
      });
      const result = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(result.detail || 'Action failed');
      }
      return result;
    },
  };

  window.LeadsBulk = window.LeadsBulk || {};
  window.LeadsBulk.api = api;
})();
