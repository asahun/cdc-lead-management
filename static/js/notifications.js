/**
 * Toast notification system for user feedback.
 * Replaces alert() popups with friendly, auto-dismissing notifications.
 */

(function() {
  'use strict';

  let notificationContainer = null;

  function initContainer() {
    if (notificationContainer) {
      return;
    }

    notificationContainer = document.createElement('div');
    notificationContainer.id = 'notification-container';
    notificationContainer.className = 'notification-container';
    document.body.appendChild(notificationContainer);
  }

  function showNotification(message, type = 'info', duration = 4000) {
    initContainer();

    const notification = document.createElement('div');
    notification.className = `notification notification-${type}`;
    notification.setAttribute('role', 'alert');
    notification.setAttribute('aria-live', 'polite');

    // Icon based on type
    let icon = 'ℹ️';
    if (type === 'success') {
      icon = '✓';
    } else if (type === 'error') {
      icon = '✕';
    } else if (type === 'warning') {
      icon = '⚠';
    }

    notification.innerHTML = `
      <span class="notification-icon">${icon}</span>
      <span class="notification-message">${escapeHtml(message)}</span>
    `;

    notificationContainer.appendChild(notification);

    // Trigger animation
    requestAnimationFrame(() => {
      notification.classList.add('notification-show');
    });

    // Auto-dismiss
    const timeout = setTimeout(() => {
      dismissNotification(notification);
    }, duration);

    // Allow manual dismiss on click
    notification.addEventListener('click', () => {
      clearTimeout(timeout);
      dismissNotification(notification);
    });

    return notification;
  }

  function dismissNotification(notification) {
    notification.classList.remove('notification-show');
    notification.classList.add('notification-hide');

    setTimeout(() => {
      if (notification.parentNode) {
        notification.parentNode.removeChild(notification);
      }
    }, 300);
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // Public API
  window.showNotification = function(message, type, duration) {
    return showNotification(message, type, duration);
  };

  window.showSuccess = function(message, duration) {
    return showNotification(message, 'success', duration);
  };

  window.showError = function(message, duration) {
    return showNotification(message, 'error', duration);
  };

  window.showWarning = function(message, duration) {
    return showNotification(message, 'warning', duration);
  };

  window.showInfo = function(message, duration) {
    return showNotification(message, 'info', duration);
  };
})();

