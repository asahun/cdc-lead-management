(function () {
  'use strict';

  const api = {
    async fetchSosOptions(baseEndpoint, flip) {
      const url = `${baseEndpoint}/sos-options${flip ? '?flip=true' : ''}`;
      const resp = await fetch(url, { headers: { Accept: 'application/json' } });
      if (!resp.ok) {
        throw new Error(`SOS options failed (${resp.status})`);
      }
      return resp.json();
    },

    async runAnalysis(baseEndpoint, body) {
      const runEndpoint = `${baseEndpoint}/run`;
      const resp = await fetch(runEndpoint, {
        method: 'POST',
        headers: {
          Accept: 'application/json',
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(body),
      });
      if (!resp.ok) {
        throw new Error(`Request failed (${resp.status})`);
      }
      return resp.json();
    },
  };

  window.EntityIntel = window.EntityIntel || {};
  window.EntityIntel.api = api;
})();
