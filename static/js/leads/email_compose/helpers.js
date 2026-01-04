(function () {
  'use strict';

  function getActiveProfileKey() {
    if (typeof window.getCurrentProfile === 'function') {
      const profile = window.getCurrentProfile();
      if (profile && profile.key) {
        return profile.key;
      }
    }
    return 'fisseha';
  }

  function combineDateTime(dateStr, timeStr) {
    if (!dateStr || !timeStr) return null;
    return `${dateStr}T${timeStr}`;
  }

  function validateBusinessHours(dateStr, timeStr) {
    if (!dateStr || !timeStr) {
      return { valid: false, message: 'Please select both date and time' };
    }

    const dateTimeStr = combineDateTime(dateStr, timeStr);
    const selectedDate = new Date(dateTimeStr);

    if (Number.isNaN(selectedDate.getTime())) {
      return { valid: false, message: 'Invalid date or time' };
    }

    const dayOfWeek = selectedDate.getDay();
    const hours = selectedDate.getHours();
    const minutes = selectedDate.getMinutes();
    const timeInMinutes = hours * 60 + minutes;

    if (dayOfWeek === 0 || dayOfWeek === 6) {
      return { valid: false, message: 'Scheduling is only available Monday-Friday' };
    }

    const startTime = 7 * 60;
    const endTime = 17 * 60;

    if (timeInMinutes < startTime || timeInMinutes >= endTime) {
      return { valid: false, message: 'Scheduling is only available between 7:00 AM and 5:00 PM' };
    }

    if (selectedDate <= new Date()) {
      return { valid: false, message: 'Scheduled time must be in the future' };
    }

    return { valid: true };
  }

  function setScheduleRequired(dateInput, timeInput, isRequired) {
    if (!dateInput || !timeInput) {
      return;
    }
    if (isRequired) {
      dateInput.setAttribute('required', 'required');
      timeInput.setAttribute('required', 'required');
    } else {
      dateInput.removeAttribute('required');
      timeInput.removeAttribute('required');
    }
  }

  function toggleScheduleMode(sendBtn, scheduleBtn, isScheduleMode) {
    if (!sendBtn || !scheduleBtn) return;
    if (isScheduleMode) {
      sendBtn.style.display = 'none';
      scheduleBtn.textContent = 'Schedule Email';
    } else {
      sendBtn.style.display = 'inline-flex';
      scheduleBtn.textContent = 'Schedule';
    }
  }

  window.EmailCompose = window.EmailCompose || {};
  window.EmailCompose.helpers = {
    getActiveProfileKey,
    combineDateTime,
    validateBusinessHours,
    setScheduleRequired,
    toggleScheduleMode,
  };
})();
