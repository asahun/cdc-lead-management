(function () {
  'use strict';

  function buildDetailUrl(path, options = {}) {
    const url = new URL(path, window.location.origin);
    if (options.context) {
      url.searchParams.set('context', options.context);
    }
    return url.toString();
  }

  window.PropertyDetail = window.PropertyDetail || {};
  window.PropertyDetail.helpers = { buildDetailUrl };
})();
