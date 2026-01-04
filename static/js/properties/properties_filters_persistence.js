// properties_filters_persistence.js
// Session-based filter persistence for properties list

(function () {
  'use strict';

  const STORAGE_KEY = 'lead_app.properties.filters.session';
  const FILTER_PARAMS = ['q', 'year', 'claim_authority'];

  const storageAvailable = (() => {
    try {
      const testKey = '__lead_app_session_test__';
      window.sessionStorage.setItem(testKey, '1');
      window.sessionStorage.removeItem(testKey);
      return true;
    } catch {
      return false;
    }
  })();

  if (!storageAvailable) {
    return;
  }

  function getFiltersFromURL() {
    const params = new URLSearchParams(window.location.search);
    const filters = {};
    FILTER_PARAMS.forEach((param) => {
      const value = params.get(param);
      if (value !== null && value !== '') {
        filters[param] = value;
      }
    });
    return filters;
  }

  function saveFilters() {
    const filters = getFiltersFromURL();
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(filters));
    } catch {
      // Ignore storage errors.
    }
  }

  function loadFilters() {
    try {
      const stored = window.sessionStorage.getItem(STORAGE_KEY);
      if (!stored) return null;
      return JSON.parse(stored);
    } catch {
      return null;
    }
  }

  function restoreFiltersIfNeeded() {
    if (!window.location.pathname.match(/^\/properties\/?$/)) {
      return false;
    }

    const urlParams = new URLSearchParams(window.location.search);
    const hasFilters = FILTER_PARAMS.some((param) => {
      const value = urlParams.get(param);
      return value !== null && value !== '';
    });

    if (hasFilters) {
      saveFilters();
      return false;
    }

    const storedFilters = loadFilters();
    if (!storedFilters || Object.keys(storedFilters).length === 0) {
      return false;
    }

    const newParams = new URLSearchParams(window.location.search);
    Object.entries(storedFilters).forEach(([key, value]) => {
      if (value !== null && value !== '') {
        newParams.set(key, value);
      }
    });

    const newSearch = newParams.toString();
    const newUrl = newSearch
      ? `${window.location.pathname}?${newSearch}`
      : window.location.pathname;

    if (newUrl !== window.location.href) {
      window.location.replace(newUrl);
      return true;
    }

    return false;
  }

  if (window.location.pathname.match(/^\/properties\/?$/)) {
    if (restoreFiltersIfNeeded()) {
      return;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    if (!window.location.pathname.match(/^\/properties\/?$/)) {
      return;
    }

    saveFilters();

    const filtersForm = document.getElementById('filters-form');
    if (filtersForm) {
      filtersForm.addEventListener('submit', () => {
        setTimeout(() => {
          saveFilters();
        }, 100);
      });
    }

    const searchForm = document.querySelector('.page-actions form');
    if (searchForm) {
      searchForm.addEventListener('submit', () => {
        setTimeout(() => {
          saveFilters();
        }, 100);
      });
    }

    const pagerLinks = document.querySelectorAll('.pager-buttons a');
    pagerLinks.forEach((link) => {
      link.addEventListener('click', () => {
        try {
          const url = new URL(link.href, window.location.origin);
          const params = new URLSearchParams(url.search);
          const filters = {};
          FILTER_PARAMS.forEach((param) => {
            const value = params.get(param);
            if (value !== null && value !== '') {
              filters[param] = value;
            }
          });
          window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(filters));
        } catch {
          // Ignore errors.
        }
      });
    });
  });
})();
