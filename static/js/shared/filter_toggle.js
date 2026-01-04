/**
 * Filter Sidebar Toggle
 * Handles collapsing/expanding the filter sidebar with localStorage persistence
 */

(function() {
  'use strict';

  const STORAGE_KEY = 'lead_app.filters.collapsed';
  const toggleBtn = document.getElementById('filter-toggle');
  const sidebar = document.getElementById('filters-sidebar');

  if (!toggleBtn || !sidebar) return;

  // Load saved state from localStorage
  function loadState() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      return saved === 'true';
    } catch (e) {
      return false;
    }
  }

  // Save state to localStorage
  function saveState(collapsed) {
    try {
      localStorage.setItem(STORAGE_KEY, collapsed ? 'true' : 'false');
    } catch (e) {
      // Ignore storage errors
    }
  }

  // Toggle sidebar
  function toggleSidebar() {
    const isCollapsed = sidebar.classList.contains('collapsed');
    
    if (isCollapsed) {
      sidebar.classList.remove('collapsed');
      toggleBtn.classList.remove('collapsed');
    } else {
      sidebar.classList.add('collapsed');
      toggleBtn.classList.add('collapsed');
    }
    
    saveState(!isCollapsed);
  }

  // Initialize state - default to collapsed if no saved state
  function init() {
    const saved = loadState();
    // Default to collapsed (true) if no saved state exists
    const shouldCollapse = saved !== null ? saved : true;
    
    if (shouldCollapse) {
      sidebar.classList.add('collapsed');
      toggleBtn.classList.add('collapsed');
      saveState(true); // Save default state
    }
  }

  // Event listener
  toggleBtn.addEventListener('click', function(e) {
    e.preventDefault();
    e.stopPropagation();
    toggleSidebar();
  });

  // Initialize on page load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

