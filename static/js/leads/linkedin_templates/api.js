(function () {
  'use strict';

  const api = {
    async loadTemplates(leadId, contactId) {
      const response = await fetch(
        `/leads/${leadId}/linkedin-templates?contact_id=${contactId}`
      );
      if (!response.ok) {
        throw new Error('Failed to load templates');
      }
      return response.json();
    },

    async loadPreview(leadId, contactId, templateName, profileKey) {
      const response = await fetch(
        `/leads/${leadId}/contacts/${contactId}/linkedin-preview?template_name=${encodeURIComponent(
          templateName
        )}&profile=${encodeURIComponent(profileKey)}`
      );
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to load preview');
      }
      return response.json();
    },

    async markSent(leadId, contactId, templateName, templateCategory) {
      const formData = new FormData();
      formData.append('template_name', templateName);
      formData.append('template_category', templateCategory);

      const response = await fetch(
        `/leads/${leadId}/contacts/${contactId}/linkedin-mark-sent`,
        { method: 'POST', body: formData }
      );
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to mark message as sent');
      }
      return response.json();
    },

    async markConnectionAccepted(leadId, contactId) {
      const response = await fetch(
        `/leads/${leadId}/contacts/${contactId}/linkedin-connection-accepted`,
        { method: 'POST' }
      );
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Failed to mark connection as accepted');
      }
      return response.json();
    },
  };

  window.LinkedInTemplates = window.LinkedInTemplates || {};
  window.LinkedInTemplates.api = api;
})();
