// year_persistence.js
// Handle year selection persistence across pages

(function() {
  'use strict';

  const YEAR_STORAGE_KEY = 'selected_year';
  const DEFAULT_YEAR = '2025';

  /**
   * Save selected year to sessionStorage
   */
  function saveYear(year) {
    if (year) {
      sessionStorage.setItem(YEAR_STORAGE_KEY, year);
    }
  }

  /**
   * Load selected year from sessionStorage
   */
  function loadYear() {
    return sessionStorage.getItem(YEAR_STORAGE_KEY) || DEFAULT_YEAR;
  }

  /**
   * Restore year from sessionStorage if not in URL
   */
  function restoreYearIfNeeded() {
    const urlParams = new URLSearchParams(window.location.search);
    const yearInUrl = urlParams.get('year');
    
    if (!yearInUrl) {
      const savedYear = loadYear();
      if (savedYear && savedYear !== DEFAULT_YEAR) {
        urlParams.set('year', savedYear);
        const newUrl = window.location.pathname + '?' + urlParams.toString();
        window.location.replace(newUrl);
      }
    } else {
      saveYear(yearInUrl);
    }
  }

  /**
   * Update year in current URL without reload
   */
  function updateYearInUrl(year) {
    const url = new URL(window.location);
    url.searchParams.set('year', year);
    window.history.replaceState({}, '', url);
    saveYear(year);
  }

  // Auto-restore on properties and leads pages
  if (window.location.pathname === '/properties' || 
      window.location.pathname === '/' ||
      window.location.pathname === '/leads') {
    restoreYearIfNeeded();
  }

  // Listen for year selector changes (only on properties page, not leads)
  document.addEventListener('change', function(e) {
    if (e.target && e.target.id === 'year' && !e.target.disabled) {
      const year = e.target.value;
      saveYear(year);
      
      // If on properties page, update URL and reload
      if (window.location.pathname === '/properties' || window.location.pathname === '/') {
        updateYearInUrl(year);
        // Reload to apply new year filter
        window.location.reload();
      }
    }
  });

  // Export functions for use in other scripts
  window.yearPersistence = {
    save: saveYear,
    load: loadYear,
    updateUrl: updateYearInUrl
  };
})();

