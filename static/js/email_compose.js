/**
 * Email composition modal and sending functionality.
 */

(function() {
  'use strict';

  const modal = document.getElementById('email-modal');
  const form = document.getElementById('email-form');
  const toInput = document.getElementById('email-to');
  const subjectInput = document.getElementById('email-subject');
  const bodyEditor = document.getElementById('email-body-editor');
  const bodyHidden = document.getElementById('email-body-hidden');
  const sendBtn = document.getElementById('email-send-btn');
  const scheduleBtn = document.getElementById('email-schedule-btn');
  const closeButtons = document.querySelectorAll('.modal-close');

  let currentLeadId = null;
  let currentContactId = null;
  
  // Expose helper for other modules (scheduled_emails.js) to update context
  window.emailComposeModule = {
    setContext({ leadId, contactId }) {
      currentLeadId = leadId;
      currentContactId = contactId;
    },
    clearContext() {
      currentLeadId = null;
      currentContactId = null;
      window.currentScheduledEmailId = null;
    },
    getContext() {
      return { leadId: currentLeadId, contactId: currentContactId };
    },
  };

  function getActiveProfileKey() {
    if (typeof window.getCurrentProfile === 'function') {
      const profile = window.getCurrentProfile();
      if (profile && profile.key) {
        return profile.key;
      }
    }
    return 'fisseha';
  }

  // Helper to reset modal
  function resetModal() {
    modal.style.display = 'none';
    form.reset();
    bodyEditor.innerHTML = '';
    const scheduleGroup = document.getElementById('schedule-group');
    if (scheduleGroup) {
      scheduleGroup.style.display = 'none';
      setScheduleRequired(false);
    }
    if (scheduleBtn) {
      toggleScheduleMode(false);
    }
    window.emailComposeModule.clearContext();
  }

  // Close modal handlers
  closeButtons.forEach(btn => {
    btn.addEventListener('click', resetModal);
  });

  // Close on outside click
  modal.addEventListener('click', (e) => {
    if (e.target === modal) {
      resetModal();
    }
  });

  // Handle prep email button clicks
  document.addEventListener('click', async (e) => {
    const btn = e.target.closest('.prep-email-btn');
    if (!btn) return;

    e.preventDefault();
    e.stopPropagation();

    const leadId = btn.dataset.leadId;
    const contactId = btn.dataset.contactId;
    const contactEmail = btn.dataset.contactEmail;
    const contactName = btn.dataset.contactName;

    if (!leadId || !contactId || !contactEmail) {
      showError('Missing contact information');
      return;
    }

    window.currentScheduledEmailId = null; // Clear any scheduled email ID
    window.emailComposeModule.setContext({ leadId, contactId });

    // Reset schedule group
    const scheduleGroup = document.getElementById('schedule-group');
    if (scheduleGroup) {
      scheduleGroup.style.display = 'none';
    }
    toggleScheduleMode(false);

    // Show loading state
    sendBtn.disabled = true;
    sendBtn.textContent = 'Loading...';
    bodyEditor.innerHTML = '<p style="color: #666;">Loading email template...</p>';

    // Open modal
    modal.style.display = 'flex';
    toInput.value = `${contactName} <${contactEmail}>`;

    try {
      const profileKey = getActiveProfileKey();
      // Fetch email content
      const response = await fetch(`/leads/${leadId}/contacts/${contactId}/prep-email?profile=${encodeURIComponent(profileKey)}`);
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to load email template');
      }

      const data = await response.json();
      subjectInput.value = data.subject || '';
      bodyEditor.innerHTML = data.body || '<p>No template available. Please compose manually.</p>';

      // Sync hidden input for form submission
      bodyHidden.value = bodyEditor.innerHTML;

      sendBtn.disabled = false;
      sendBtn.textContent = 'Send';
    } catch (error) {
      console.error('Error loading email:', error);
      showError('Failed to load email template: ' + error.message);
      bodyEditor.innerHTML = '<p style="color: #d32f2f;">Error loading template. Please compose manually.</p>';
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send';
    }
  });

  // Sync body editor to hidden input
  bodyEditor.addEventListener('input', () => {
    bodyHidden.value = bodyEditor.innerHTML;
  });

  // Handle form submission
  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!currentLeadId) {
      showError('Missing lead information');
      return;
    }

    const subject = subjectInput.value.trim();
    const body = bodyHidden.value || bodyEditor.innerHTML;
    const profileKey = getActiveProfileKey();

    if (!subject) {
      showError('Subject is required');
      return;
    }

    if (!body || body.trim() === '') {
      showError('Email body is required');
      return;
    }

    // Check if we're editing a scheduled email
    if (window.currentScheduledEmailId) {
      // Update the scheduled email and send it now
      sendBtn.disabled = true;
      sendBtn.textContent = 'Sending...';
      scheduleBtn.disabled = true;

      try {
        // First update the scheduled email
        const updateFormData = new FormData();
        updateFormData.append('subject', subject);
        updateFormData.append('body', body);
        updateFormData.append('profile', profileKey);

        const updateResponse = await fetch(`/leads/${currentLeadId}/scheduled-emails/${window.currentScheduledEmailId}`, {
          method: 'PUT',
          body: updateFormData,
        });

        if (!updateResponse.ok) {
          const error = await updateResponse.json();
          throw new Error(error.detail || 'Failed to update scheduled email');
        }

        // Then send it now
        const sendResponse = await fetch(`/leads/${currentLeadId}/scheduled-emails/${window.currentScheduledEmailId}/send-now`, {
          method: 'POST',
        });

        if (!sendResponse.ok) {
          const error = await sendResponse.json();
          throw new Error(error.detail || 'Failed to send email');
        }

        showSuccess('Email updated and sent successfully!');
        resetModal();
        window.currentScheduledEmailId = null;
        window.location.reload();
      } catch (error) {
        console.error('Error updating/sending email:', error);
        showError('Failed to update/send email: ' + error.message);
        sendBtn.disabled = false;
        sendBtn.textContent = 'Send Now';
        scheduleBtn.disabled = false;
      }
      return;
    }

    // Regular send (not editing scheduled email)
    if (!currentContactId) {
      showError('Missing contact information');
      return;
    }

    // Disable buttons during send
    sendBtn.disabled = true;
    sendBtn.textContent = 'Sending...';
    scheduleBtn.disabled = true;

    try {
      const formData = new FormData();
      formData.append('subject', subject);
      formData.append('body', body);

      formData.append('profile', profileKey);

      const response = await fetch(`/leads/${currentLeadId}/contacts/${currentContactId}/send-email`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to send email');
      }

      const result = await response.json();
      showSuccess('Email sent successfully!');
      resetModal();

      // Reload page to show new attempt
      window.location.reload();
    } catch (error) {
      console.error('Error sending email:', error);
      showError('Failed to send email: ' + error.message);
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send';
      scheduleBtn.disabled = false;
    }
  });

  // Schedule button handler
  const scheduleGroup = document.getElementById('schedule-group');
  const scheduledDateInput = document.getElementById('email-scheduled-date');
  const scheduledTimeInput = document.getElementById('email-scheduled-time');

  function setScheduleRequired(isRequired) {
    if (!scheduledDateInput || !scheduledTimeInput) {
      return;
    }
    if (isRequired) {
      scheduledDateInput.setAttribute('required', 'required');
      scheduledTimeInput.setAttribute('required', 'required');
    } else {
      scheduledDateInput.removeAttribute('required');
      scheduledTimeInput.removeAttribute('required');
    }
  }

  // hidden by default, so ensure not required initially
  setScheduleRequired(false);
  
  // Combine date and time into datetime string
  function combineDateTime(dateStr, timeStr) {
    if (!dateStr || !timeStr) return null;
    return `${dateStr}T${timeStr}`;
  }
  
  // Validate business hours
  function validateBusinessHours(dateStr, timeStr) {
    if (!dateStr || !timeStr) {
      return { valid: false, message: 'Please select both date and time' };
    }
    
    const dateTimeStr = combineDateTime(dateStr, timeStr);
    const selectedDate = new Date(dateTimeStr);
    
    // Check if valid date
    if (isNaN(selectedDate.getTime())) {
      return { valid: false, message: 'Invalid date or time' };
    }
    
    const dayOfWeek = selectedDate.getDay();
    const hours = selectedDate.getHours();
    const minutes = selectedDate.getMinutes();
    const timeInMinutes = hours * 60 + minutes;
    
    // Check if weekend
    if (dayOfWeek === 0 || dayOfWeek === 6) {
      return { valid: false, message: 'Scheduling is only available Monday-Friday' };
    }
    
    // Check if within business hours (7 AM - 5 PM)
    const startTime = 7 * 60; // 7:00 AM in minutes
    const endTime = 17 * 60; // 5:00 PM in minutes
    
    if (timeInMinutes < startTime || timeInMinutes >= endTime) {
      return { valid: false, message: 'Scheduling is only available between 7:00 AM and 5:00 PM' };
    }
    
    // Check if in the future
    if (selectedDate <= new Date()) {
      return { valid: false, message: 'Scheduled time must be in the future' };
    }
    
    return { valid: true };
  }

  // Hide Send button when schedule is visible
  function toggleScheduleMode(isScheduleMode) {
    if (isScheduleMode) {
      sendBtn.style.display = 'none';
      scheduleBtn.textContent = 'Schedule Email';
    } else {
      sendBtn.style.display = 'inline-flex';
      scheduleBtn.textContent = 'Schedule';
    }
  }

  scheduleBtn.addEventListener('click', async (e) => {
    e.preventDefault();
    
    // Toggle schedule input visibility
    if (scheduleGroup.style.display === 'none') {
      // Show schedule input
      scheduleGroup.style.display = 'block';
      toggleScheduleMode(true);
      setScheduleRequired(true);
      
      // Set default to next business day at 9 AM
      const now = new Date();
      const tomorrow = new Date(now);
      tomorrow.setDate(tomorrow.getDate() + 1);
      
      // If tomorrow is weekend, move to Monday
      while (tomorrow.getDay() === 0 || tomorrow.getDay() === 6) {
        tomorrow.setDate(tomorrow.getDate() + 1);
      }
      
      tomorrow.setHours(9, 0, 0, 0);
      
      // Format for date input (YYYY-MM-DD)
      const year = tomorrow.getFullYear();
      const month = String(tomorrow.getMonth() + 1).padStart(2, '0');
      const day = String(tomorrow.getDate()).padStart(2, '0');
      
      // Format for time input (HH:mm)
      const hours = String(tomorrow.getHours()).padStart(2, '0');
      const minutes = String(tomorrow.getMinutes()).padStart(2, '0');
      
      scheduledDateInput.value = `${year}-${month}-${day}`;
      scheduledTimeInput.value = `${hours}:${minutes}`;
    } else {
      const subject = subjectInput.value.trim();
      const body = bodyHidden.value || bodyEditor.innerHTML;
      const scheduledDate = scheduledDateInput.value;
      const scheduledTime = scheduledTimeInput.value;
      const profileKey = getActiveProfileKey();

      if (!subject) {
        showError('Subject is required');
        return;
      }

      if (!body || body.trim() === '') {
        showError('Email body is required');
        return;
      }

      const validation = validateBusinessHours(scheduledDate, scheduledTime);
      if (!validation.valid) {
        showError(validation.message);
        return;
      }

      // Combine date and time, then convert to ISO string for backend
      const dateTimeStr = combineDateTime(scheduledDate, scheduledTime);
      const localDate = new Date(dateTimeStr);
      const isoString = localDate.toISOString();

      // Editing an existing scheduled email (no contact needed)
      if (window.currentScheduledEmailId) {
        scheduleBtn.disabled = true;
        scheduleBtn.textContent = 'Updating...';

        try {
          const formData = new FormData();
          formData.append('subject', subject);
          formData.append('body', body);
          formData.append('scheduled_at', isoString);
          formData.append('profile', profileKey);

          const response = await fetch(`/leads/${currentLeadId}/scheduled-emails/${window.currentScheduledEmailId}`, {
            method: 'PUT',
            body: formData,
          });

          if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Failed to update scheduled email');
          }

          showSuccess('Scheduled email updated!');
          resetModal();
          window.currentScheduledEmailId = null;
          window.location.reload();
        } catch (error) {
          console.error('Error updating scheduled email:', error);
          showError('Failed to update scheduled email: ' + error.message);
          scheduleBtn.disabled = false;
          scheduleBtn.textContent = 'Schedule Email';
        }

        return;
      }

      // Creating a brand new scheduled email (requires contact)
      if (!currentLeadId || !currentContactId) {
        showError('Missing lead or contact information');
        return;
      }

      // Disable button during schedule
      scheduleBtn.disabled = true;
      scheduleBtn.textContent = 'Scheduling...';

      try {
        const formData = new FormData();
        formData.append('subject', subject);
        formData.append('body', body);
        formData.append('scheduled_at', isoString);
        formData.append('profile', profileKey);

        const response = await fetch(`/leads/${currentLeadId}/contacts/${currentContactId}/schedule-email`, {
          method: 'POST',
          body: formData,
        });

        if (!response.ok) {
          const error = await response.json();
          throw new Error(error.detail || 'Failed to schedule email');
        }

        showSuccess('Email scheduled successfully!');
        modal.style.display = 'none';
        form.reset();
        bodyEditor.innerHTML = '';
        scheduleGroup.style.display = 'none';
        toggleScheduleMode(false);
        scheduledDateInput.value = '';
        scheduledTimeInput.value = '';
        setScheduleRequired(false);
        window.emailComposeModule.clearContext();

        // Reload page to show scheduled email
        window.location.reload();
      } catch (error) {
        console.error('Error scheduling email:', error);
        showError('Failed to schedule email: ' + error.message);
        scheduleBtn.disabled = false;
        scheduleBtn.textContent = 'Schedule Email';
      }
    }
  });
})();

