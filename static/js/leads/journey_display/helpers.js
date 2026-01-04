(function () {
  'use strict';

  function formatDate(date) {
    const parsed = date instanceof Date ? date : new Date(date);
    return parsed.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  }

  function getStatusIcon(status) {
    switch (status) {
      case 'completed':
        return '✓';
      case 'overdue':
        return '⚠️';
      case 'skipped':
        return '⏭️';
      case 'pending':
      default:
        return '⏳';
    }
  }

  window.JourneyDisplay = window.JourneyDisplay || {};
  window.JourneyDisplay.helpers = { formatDate, getStatusIcon };
})();
