(function () {
  'use strict';

  const NAV_CONFIG = [
    {
      href: '/leads',
      storageKey: 'lead_app.leads.filters.session',
    },
    {
      href: '/properties',
      storageKey: 'lead_app.properties.filters.session',
    },
  ];

  function loadStoredFilters(storageKey) {
    try {
      const stored = window.sessionStorage.getItem(storageKey);
      if (!stored) return null;
      const parsed = JSON.parse(stored);
      return parsed && typeof parsed === 'object' ? parsed : null;
    } catch {
      return null;
    }
  }

  function buildQueryString(filters) {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, value]) => {
      if (value !== null && value !== '') {
        params.set(key, value);
      }
    });
    return params.toString();
  }

  document.addEventListener('DOMContentLoaded', () => {
    NAV_CONFIG.forEach(({ href, storageKey }) => {
      const navLinks = document.querySelectorAll(`a.nav-link[href="${href}"]`);
      if (!navLinks.length) return;

      navLinks.forEach((link) => {
        link.addEventListener('click', () => {
          const storedFilters = loadStoredFilters(storageKey);
          if (!storedFilters || Object.keys(storedFilters).length === 0) {
            return;
          }
          const queryString = buildQueryString(storedFilters);
          if (queryString) {
            link.href = `${href}?${queryString}`;
          }
        });
      });
    });
  });
})();
