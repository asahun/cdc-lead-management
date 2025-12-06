// leads_filters_persistence.js
// Session-based filter persistence for leads list
// Filters persist during tab session and clear when tab closes
// This is separate from page/search state which uses localStorage

(function() {
  'use strict';

  const STORAGE_KEY = "lead_app.leads.filters.session";
  
  // All filter parameter names
  const FILTER_PARAMS = [
    'q',
    'attempt_type',
    'attempt_operator',
    'attempt_count',
    'print_log_operator',
    'print_log_count',
    'print_log_mailed',
    'scheduled_email_operator',
    'scheduled_email_count',
    'failed_email_operator',
    'failed_email_count',
    'status',
  ];

  // Check if sessionStorage is available
  const storageAvailable = (() => {
    try {
      const testKey = "__lead_app_session_test__";
      window.sessionStorage.setItem(testKey, "1");
      window.sessionStorage.removeItem(testKey);
      return true;
    } catch {
      return false;
    }
  })();

  if (!storageAvailable) {
    return;
  }

  /**
   * Extract filter parameters from URL
   */
  function getFiltersFromURL() {
    const params = new URLSearchParams(window.location.search);
    const filters = {};
    FILTER_PARAMS.forEach(param => {
      const value = params.get(param);
      if (value !== null && value !== '') {
        filters[param] = value;
      }
    });
    return filters;
  }

  /**
   * Save current filters to sessionStorage
   */
  function saveFilters() {
    const filters = getFiltersFromURL();
    try {
      window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(filters));
    } catch (e) {
      // Ignore storage errors (e.g., quota exceeded)
      console.warn('Failed to save filters to sessionStorage:', e);
    }
  }

  /**
   * Load filters from sessionStorage
   */
  function loadFilters() {
    try {
      const stored = window.sessionStorage.getItem(STORAGE_KEY);
      if (!stored) return null;
      return JSON.parse(stored);
    } catch (e) {
      // Ignore parse errors
      return null;
    }
  }

  /**
   * Clear filters from sessionStorage
   */
  function clearFilters() {
    try {
      window.sessionStorage.removeItem(STORAGE_KEY);
    } catch (e) {
      // Ignore errors
    }
  }

  /**
   * Restore filters to URL if not present
   * Returns true if filters were restored and page should redirect
   */
  function restoreFiltersIfNeeded() {
    // Only restore on /leads page
    if (!window.location.pathname.match(/^\/leads\/?$/)) {
      return false;
    }

    const urlParams = new URLSearchParams(window.location.search);
    
    // Check if URL already has any filter parameters
    const hasFilters = FILTER_PARAMS.some(param => {
      const value = urlParams.get(param);
      return value !== null && value !== '';
    });

    // If URL has filters, use them and update storage
    if (hasFilters) {
      saveFilters();
      return false;
    }

    // Otherwise, restore from sessionStorage
    const storedFilters = loadFilters();
    if (!storedFilters || Object.keys(storedFilters).length === 0) {
      return false;
    }

    // Build new URL with stored filters
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

  // Restore filters on page load (only on /leads page)
  if (window.location.pathname.match(/^\/leads\/?$/)) {
    if (restoreFiltersIfNeeded()) {
      // Redirect happened, stop execution
      return;
    }
  }

  // Preserve filters when clicking "Leads" nav link from other pages
  // This runs on all pages, not just /leads
  document.addEventListener('DOMContentLoaded', () => {
    const navLinks = document.querySelectorAll('a.nav-link[href="/leads"]');
    navLinks.forEach(link => {
      link.addEventListener('click', (e) => {
        const storedFilters = loadFilters();
        if (storedFilters && Object.keys(storedFilters).length > 0) {
          const params = new URLSearchParams();
          Object.entries(storedFilters).forEach(([key, value]) => {
            if (value !== null && value !== '') {
              params.set(key, value);
            }
          });
          const queryString = params.toString();
          if (queryString) {
            link.href = `/leads?${queryString}`;
          }
        }
      });
    });
  });

  // Save filters when they change (only on /leads page)
  document.addEventListener('DOMContentLoaded', () => {
    // Only run on /leads page
    if (!window.location.pathname.match(/^\/leads\/?$/)) {
      return;
    }

    // Save current filters on page load
    saveFilters();

    // Save filters when filter form is submitted
    const filtersForm = document.getElementById('filters-form');
    if (filtersForm) {
      filtersForm.addEventListener('submit', () => {
        // Small delay to let URL update first
        setTimeout(() => {
          saveFilters();
        }, 100);
      });
    }

    // Save filters when search form is submitted
    const searchForm = document.querySelector('.page-actions form');
    if (searchForm) {
      searchForm.addEventListener('submit', () => {
        setTimeout(() => {
          saveFilters();
        }, 100);
      });
    }

    // Save filters when pagination links are clicked
    const pagerLinks = document.querySelectorAll('.pager-buttons a');
    pagerLinks.forEach(link => {
      link.addEventListener('click', () => {
        try {
          const url = new URL(link.href, window.location.origin);
          const params = new URLSearchParams(url.search);
          const filters = {};
          FILTER_PARAMS.forEach(param => {
            const value = params.get(param);
            if (value !== null && value !== '') {
              filters[param] = value;
            }
          });
          try {
            window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(filters));
          } catch (e) {
            // Ignore errors
          }
        } catch (e) {
          // Ignore URL parsing errors
        }
      });
    });

    // Clear filters when "Clear All" is clicked
    const clearFiltersBtn = document.getElementById('clear-filters');
    if (clearFiltersBtn) {
      clearFiltersBtn.addEventListener('click', () => {
        clearFilters();
      });
    }
  });
})();

