(function () {
  'use strict';

  const api = window.EmailCompose?.api;
  const helpers = window.EmailCompose?.helpers;
  if (!api || !helpers) return;

  const modal = document.getElementById('email-modal');
  const form = document.getElementById('email-form');
  const toInput = document.getElementById('email-to');
  const subjectInput = document.getElementById('email-subject');
  const bodyEditor = document.getElementById('email-body-editor');
  const bodyHidden = document.getElementById('email-body-hidden');
  const sendBtn = document.getElementById('email-send-btn');
  const scheduleBtn = document.getElementById('email-schedule-btn');
  const closeButtons = document.querySelectorAll('.modal-close');

  const scheduleGroup = document.getElementById('schedule-group');
  const scheduledDateInput = document.getElementById('email-scheduled-date');
  const scheduledTimeInput = document.getElementById('email-scheduled-time');

  let currentLeadId = null;
  let currentContactId = null;

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

  function resetModal() {
    modal.style.display = 'none';
    form.reset();
    bodyEditor.innerHTML = '';
    const templateDisplay = document.getElementById('email-template-display');
    if (templateDisplay) {
      templateDisplay.textContent = '';
      templateDisplay.style.color = '';
      templateDisplay.style.fontWeight = '';
    }
    if (scheduleGroup) {
      scheduleGroup.style.display = 'none';
      helpers.setScheduleRequired(scheduledDateInput, scheduledTimeInput, false);
    }
    if (scheduleBtn) {
      helpers.toggleScheduleMode(sendBtn, scheduleBtn, false);
      scheduleBtn.disabled = false;
      scheduleBtn.style.display = 'inline-flex';
    }
    if (sendBtn) {
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send';
    }
    if (subjectInput) {
      subjectInput.disabled = false;
    }
    window.emailComposeModule.clearContext();
  }

  async function getNextEmailTemplate(leadId) {
    try {
      const journeyData = await api.fetchJourney(leadId);
      if (!journeyData || !journeyData.email) {
        return { variant: 'initial', label: 'Initial Contact' };
      }

      const emailMilestones = journeyData.email || [];
      const nextMilestone = emailMilestones.find(
        (m) => m.status === 'pending' || m.status === 'overdue'
      );

      if (!nextMilestone) {
        return { completed: true, label: 'All Emails Sent' };
      }

      const typeToVariant = {
        email_1: { variant: 'initial', label: 'Initial Contact' },
        email_followup_1: { variant: 'followup_1', label: 'Follow-up #1' },
        email_followup_2: { variant: 'followup_2', label: 'Final Nudge' },
      };

      return typeToVariant[nextMilestone.type] || { variant: 'initial', label: 'Initial Contact' };
    } catch (error) {
      console.error('Error fetching journey data:', error);
      return { variant: 'initial', label: 'Initial Contact' };
    }
  }

  async function loadEmailTemplate(templateVariant = 'initial') {
    if (!currentLeadId || !currentContactId) {
      return;
    }

    if (!bodyEditor || !subjectInput || !bodyHidden || !sendBtn) {
      return;
    }

    const profileKey = helpers.getActiveProfileKey();
    sendBtn.disabled = true;
    sendBtn.textContent = 'Loading...';
    bodyEditor.innerHTML = '<p style="color: #666;">Loading email template...</p>';

    try {
      const data = await api.prepEmail(currentLeadId, currentContactId, profileKey, templateVariant);
      subjectInput.value = data.subject || '';
      bodyEditor.innerHTML = data.body || '<p>No template available. Please compose manually.</p>';
      bodyHidden.value = bodyEditor.innerHTML;

      sendBtn.disabled = false;
      sendBtn.textContent = 'Send';
    } catch (error) {
      console.error('Error loading email:', error);
      showError('Failed to load email template: ' + error.message);
      if (bodyEditor) {
        bodyEditor.innerHTML =
          '<p style="color: #d32f2f;">Error loading template. Please compose manually.</p>';
      }
      if (sendBtn) {
        sendBtn.disabled = false;
        sendBtn.textContent = 'Send';
      }
    }
  }

  closeButtons.forEach((btn) => {
    btn.addEventListener('click', resetModal);
  });

  modal.addEventListener('click', (e) => {
    if (e.target === modal) {
      resetModal();
    }
  });

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

    window.currentScheduledEmailId = null;
    window.emailComposeModule.setContext({ leadId, contactId });

    if (scheduleGroup) {
      scheduleGroup.style.display = 'none';
    }
    helpers.toggleScheduleMode(sendBtn, scheduleBtn, false);

    sendBtn.disabled = true;
    sendBtn.textContent = 'Loading...';
    bodyEditor.innerHTML = '<p style="color: #666;">Loading email template...</p>';

    modal.style.display = 'flex';
    toInput.value = `${contactName} <${contactEmail}>`;

    const nextTemplate = await getNextEmailTemplate(leadId);
    const templateDisplay = document.getElementById('email-template-display');

    if (nextTemplate.completed) {
      if (templateDisplay) {
        templateDisplay.textContent = nextTemplate.label;
        templateDisplay.style.color = '#4caf50';
        templateDisplay.style.fontWeight = '600';
      }

      bodyEditor.innerHTML = `
        <div style="padding: 40px 20px; text-align: center;">
          <div style="color: #4caf50; font-size: 48px; margin-bottom: 16px;">✓</div>
          <h3 style="color: #111827; margin: 0 0 8px 0; font-size: 18px;">All Emails Sent</h3>
          <p style="color: #6b7280; margin: 0; font-size: 14px;">All email outreach milestones have been completed for this contact.</p>
        </div>
      `;
      bodyHidden.value = bodyEditor.innerHTML;

      sendBtn.disabled = true;
      sendBtn.textContent = 'All Emails Sent';
      if (scheduleBtn) {
        scheduleBtn.disabled = true;
        scheduleBtn.style.display = 'none';
      }

      subjectInput.value = '';
      subjectInput.disabled = true;
      return;
    }

    if (templateDisplay) {
      templateDisplay.textContent = nextTemplate.label;
      templateDisplay.style.color = '';
      templateDisplay.style.fontWeight = '';
    }

    subjectInput.disabled = false;
    sendBtn.disabled = false;
    sendBtn.textContent = 'Send';
    if (scheduleBtn) {
      scheduleBtn.disabled = false;
      scheduleBtn.style.display = 'inline-flex';
    }

    loadEmailTemplate(nextTemplate.variant);
  });

  bodyEditor.addEventListener('input', () => {
    bodyHidden.value = bodyEditor.innerHTML;
  });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!currentLeadId) {
      showError('Missing lead information');
      return;
    }

    const subject = subjectInput.value.trim();
    const body = bodyHidden.value || bodyEditor.innerHTML;
    const profileKey = helpers.getActiveProfileKey();

    if (!subject) {
      showError('Subject is required');
      return;
    }

    if (!body || body.trim() === '') {
      showError('Email body is required');
      return;
    }

    if (window.currentScheduledEmailId) {
      sendBtn.disabled = true;
      sendBtn.textContent = 'Sending...';
      scheduleBtn.disabled = true;

      try {
        const updateFormData = new FormData();
        updateFormData.append('subject', subject);
        updateFormData.append('body', body);
        updateFormData.append('profile', profileKey);

        await api.updateScheduledEmail(currentLeadId, window.currentScheduledEmailId, updateFormData);
        await api.sendScheduledEmailNow(currentLeadId, window.currentScheduledEmailId);

        showSuccess('Email updated and sent successfully!');

        sendBtn.textContent = 'Sent!';
        sendBtn.style.backgroundColor = '#4caf50';
        sendBtn.disabled = true;

        if (scheduleBtn) {
          scheduleBtn.style.display = 'none';
        }

        window.currentScheduledEmailId = null;

        setTimeout(() => {
          resetModal();
        }, 1500);
      } catch (error) {
        console.error('Error updating/sending email:', error);
        showError('Failed to update/send email: ' + error.message);
        sendBtn.disabled = false;
        sendBtn.textContent = 'Send Now';
        scheduleBtn.disabled = false;
      }
      return;
    }

    if (!currentContactId) {
      showError('Missing contact information');
      return;
    }

    sendBtn.disabled = true;
    sendBtn.textContent = 'Sending...';
    scheduleBtn.disabled = true;

    try {
      const formData = new FormData();
      formData.append('subject', subject);
      formData.append('body', body);
      formData.append('profile', profileKey);

      await api.sendEmail(currentLeadId, currentContactId, formData);
      showSuccess('Email sent successfully!');

      sendBtn.textContent = 'Sent!';
      sendBtn.style.backgroundColor = '#4caf50';
      sendBtn.disabled = true;

      if (scheduleBtn) {
        scheduleBtn.style.display = 'none';
      }

      setTimeout(() => {
        resetModal();
      }, 1500);
    } catch (error) {
      console.error('Error sending email:', error);
      showError('Failed to send email: ' + error.message);
      sendBtn.disabled = false;
      sendBtn.textContent = 'Send';
      scheduleBtn.disabled = false;
    }
  });

  helpers.setScheduleRequired(scheduledDateInput, scheduledTimeInput, false);

  scheduleBtn.addEventListener('click', async (e) => {
    e.preventDefault();

    if (scheduleGroup.style.display === 'none') {
      scheduleGroup.style.display = 'block';
      helpers.toggleScheduleMode(sendBtn, scheduleBtn, true);
      helpers.setScheduleRequired(scheduledDateInput, scheduledTimeInput, true);

      const now = new Date();
      const tomorrow = new Date(now);
      tomorrow.setDate(tomorrow.getDate() + 1);

      while (tomorrow.getDay() === 0 || tomorrow.getDay() === 6) {
        tomorrow.setDate(tomorrow.getDate() + 1);
      }

      tomorrow.setHours(9, 0, 0, 0);

      const year = tomorrow.getFullYear();
      const month = String(tomorrow.getMonth() + 1).padStart(2, '0');
      const day = String(tomorrow.getDate()).padStart(2, '0');

      const hours = String(tomorrow.getHours()).padStart(2, '0');
      const minutes = String(tomorrow.getMinutes()).padStart(2, '0');

      scheduledDateInput.value = `${year}-${month}-${day}`;
      scheduledTimeInput.value = `${hours}:${minutes}`;
      return;
    }

    const subject = subjectInput.value.trim();
    const body = bodyHidden.value || bodyEditor.innerHTML;
    const scheduledDate = scheduledDateInput.value;
    const scheduledTime = scheduledTimeInput.value;
    const profileKey = helpers.getActiveProfileKey();

    if (!subject) {
      showError('Subject is required');
      return;
    }

    if (!body || body.trim() === '') {
      showError('Email body is required');
      return;
    }

    const validation = helpers.validateBusinessHours(scheduledDate, scheduledTime);
    if (!validation.valid) {
      showError(validation.message);
      return;
    }

    const dateTimeStr = helpers.combineDateTime(scheduledDate, scheduledTime);
    const localDate = new Date(dateTimeStr);
    const isoString = localDate.toISOString();

    if (window.currentScheduledEmailId) {
      scheduleBtn.disabled = true;
      scheduleBtn.textContent = 'Updating...';

      try {
        const formData = new FormData();
        formData.append('subject', subject);
        formData.append('body', body);
        formData.append('scheduled_at', isoString);
        formData.append('profile', profileKey);

        await api.updateScheduledEmail(currentLeadId, window.currentScheduledEmailId, formData);

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

    if (!currentLeadId || !currentContactId) {
      showError('Missing lead or contact information');
      return;
    }

    scheduleBtn.disabled = true;
    scheduleBtn.textContent = 'Scheduling...';

    try {
      const formData = new FormData();
      formData.append('subject', subject);
      formData.append('body', body);
      formData.append('scheduled_at', isoString);
      formData.append('profile', profileKey);

      await api.scheduleEmail(currentLeadId, currentContactId, formData);

      showSuccess('Email scheduled successfully!');
      modal.style.display = 'none';
      form.reset();
      bodyEditor.innerHTML = '';
      scheduleGroup.style.display = 'none';
      helpers.toggleScheduleMode(sendBtn, scheduleBtn, false);
      scheduledDateInput.value = '';
      scheduledTimeInput.value = '';
      helpers.setScheduleRequired(scheduledDateInput, scheduledTimeInput, false);
      window.emailComposeModule.clearContext();

      window.location.reload();
    } catch (error) {
      console.error('Error scheduling email:', error);
      showError('Failed to schedule email: ' + error.message);
      scheduleBtn.disabled = false;
      scheduleBtn.textContent = 'Schedule Email';
    }
  });
})();
