(function () {
  'use strict';

  const api = {
    async fetchLatest(baseEndpoint) {
      const response = await fetch(`${baseEndpoint}/latest`);
      if (!response.ok) {
        throw new Error('Failed to load agent intel');
      }
      return response.json();
    },

    async run(baseEndpoint) {
      const response = await fetch(`${baseEndpoint}/run`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!response.ok) {
        throw new Error('Agent run failed');
      }
      return response.json();
    },
  };

  window.AgentIntel = window.AgentIntel || {};
  window.AgentIntel.api = api;
})();
