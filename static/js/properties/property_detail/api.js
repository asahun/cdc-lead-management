(function () {
  'use strict';

  const api = {
    async fetchDetail(url) {
      const response = await fetch(url);
      if (!response.ok) {
        throw new Error('Unable to load property details');
      }
      return response.text();
    },
  };

  window.PropertyDetail = window.PropertyDetail || {};
  window.PropertyDetail.api = api;
})();
