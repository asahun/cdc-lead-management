(function () {
  'use strict';

  const api = {
    async fetchEvents(claimId) {
      const res = await fetch(`/claims/${claimId}/events`);
      if (!res.ok) return [];
      const data = await res.json();
      return data.events || [];
    },

    async fetchDocuments(claimId) {
      const [genRes, pkgRes, historyRes] = await Promise.all([
        fetch(`/claims/${claimId}/files?type=generated`),
        fetch(`/claims/${claimId}/files?type=package`),
        fetch(`/claims/${claimId}/documents`),
      ]);

      return {
        generated: genRes.ok ? (await genRes.json()).files || [] : [],
        packaged: pkgRes.ok ? (await pkgRes.json()).files || [] : [],
        history: historyRes.ok ? (await historyRes.json()).documents || [] : [],
      };
    },

    async deleteFile(claimId, type, name) {
      const res = await fetch(
        `/claims/${claimId}/files?type=${encodeURIComponent(type)}&name=${encodeURIComponent(name)}`,
        { method: 'DELETE' }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Delete failed');
      }
      return res.json().catch(() => ({}));
    },

    async uploadDocument(claimId, formData) {
      const res = await fetch(`/claims/${claimId}/documents/upload`, {
        method: 'POST',
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Upload failed');
      }
      return res.json();
    },

    async saveClientInfo(claimId, payload) {
      const res = await fetch(`/claims/${claimId}/client-info`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Save failed');
      }
      return res.json();
    },

    async generateAgreements(claimId, payload) {
      const res = await fetch(`/claims/${claimId}/agreements/generate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Generation failed');
      }
      return res.json();
    },

    async updateStatus(claimId, state) {
      const res = await fetch(`/claims/${claimId}/status`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ state }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to update status');
      }
      return res.json();
    },
  };

  window.ClaimDetail = window.ClaimDetail || {};
  window.ClaimDetail.api = api;
})();
