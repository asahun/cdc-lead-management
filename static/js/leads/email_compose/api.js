(function () {
  'use strict';

  const api = {
    async fetchJourney(leadId) {
      const response = await fetch(`/api/leads/${leadId}/journey`);
      if (!response.ok) {
        return null;
      }
      return response.json();
    },

    async prepEmail(leadId, contactId, profileKey, templateVariant) {
      const url = `/leads/${leadId}/contacts/${contactId}/prep-email?profile=${encodeURIComponent(
        profileKey
      )}&template_variant=${encodeURIComponent(templateVariant)}`;
      const response = await fetch(url);
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to load email template');
      }
      return response.json();
    },

    async updateScheduledEmail(leadId, scheduledId, formData) {
      const response = await fetch(`/leads/${leadId}/scheduled-emails/${scheduledId}`, {
        method: 'PUT',
        body: formData,
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to update scheduled email');
      }
      return response.json();
    },

    async sendScheduledEmailNow(leadId, scheduledId) {
      const response = await fetch(
        `/leads/${leadId}/scheduled-emails/${scheduledId}/send-now`,
        { method: 'POST' }
      );
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to send email');
      }
      return response.json();
    },

    async sendEmail(leadId, contactId, formData) {
      const response = await fetch(
        `/leads/${leadId}/contacts/${contactId}/send-email`,
        { method: 'POST', body: formData }
      );
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to send email');
      }
      return response.json();
    },

    async scheduleEmail(leadId, contactId, formData) {
      const response = await fetch(
        `/leads/${leadId}/contacts/${contactId}/schedule-email`,
        { method: 'POST', body: formData }
      );
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to schedule email');
      }
      return response.json();
    },
  };

  window.EmailCompose = window.EmailCompose || {};
  window.EmailCompose.api = api;
})();
