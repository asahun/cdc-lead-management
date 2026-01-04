(function () {
  'use strict';

  const api = {
    async fetchPrintLogs(leadId) {
      const response = await fetch(`/leads/${leadId}/print-logs`, {
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        throw new Error('Failed to refresh print log');
      }
      return response.json();
    },

    async markPrintLogMailed(leadId, logId) {
      const response = await fetch(`/leads/${leadId}/print-logs/${logId}/mark-mailed`, {
        method: 'POST',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || 'Failed to mark as mailed');
      }
      return response.json().catch(() => ({}));
    },

    async deletePrintLog(leadId, logId) {
      const response = await fetch(`/leads/${leadId}/print-logs/${logId}`, {
        method: 'DELETE',
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) {
        const text = await response.text();
        throw new Error(text || 'Failed to delete print log');
      }
      return response.json().catch(() => ({}));
    },

    async refreshAttempts(leadId) {
      const response = await fetch(`/leads/${leadId}/edit`);
      if (!response.ok) {
        throw new Error('Failed to refresh attempts');
      }
      return response.text();
    },

    async generateLetter(url) {
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'X-Requested-With': 'fetch',
          Accept: 'application/pdf',
        },
      });
      if (!response.ok) {
        let message = 'Unable to generate letter.';
        try {
          const data = await response.json();
          if (data && data.detail) {
            message = data.detail;
          }
        } catch {
          const text = await response.text();
          if (text) {
            message = text;
          }
        }
        throw new Error(message);
      }
      const blob = await response.blob();
      const disposition = response.headers.get('Content-Disposition') || '';
      return { blob, disposition };
    },
  };

  window.LetterPrint = window.LetterPrint || {};
  window.LetterPrint.api = api;
})();
