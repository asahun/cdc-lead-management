(function () {
  'use strict';

  const api = window.LinkedInTemplates?.api;
  const helpers = window.LinkedInTemplates?.helpers;
  if (!api || !helpers) return;

  const modal = document.getElementById('linkedin-modal');
  const templatesContainer = document.getElementById('linkedin-templates-container');
  const previewContent = document.getElementById('linkedin-preview-content');
  const subjectSection = document.getElementById('linkedin-subject-section');
  const subjectContent = document.getElementById('linkedin-subject-content');
  const copySubjectBtn = document.getElementById('linkedin-copy-subject-btn');
  const copyBtn = document.getElementById('linkedin-copy-btn');
  const markSentBtn = document.getElementById('linkedin-mark-sent-btn');
  const followupIndicator = document.getElementById('linkedin-followup-indicator');
  const profileLabel = document.getElementById('linkedin-profile-label');
  const tabs = document.querySelectorAll('.linkedin-tab');
  const closeButtons = document.querySelectorAll('#linkedin-modal .modal-close');
  const connectionStatusContainer = document.getElementById('linkedin-connection-status');
  const connectionStatusText = document.getElementById('linkedin-connection-status-text');
  const markConnectionAcceptedBtn = document.getElementById('linkedin-mark-connection-accepted-btn');

  const profileChip = document.querySelector('[data-profile-label]');

  let currentLeadId = null;
  let currentContactId = null;
  let currentTemplateName = null;
  let currentTemplateCategory = null;
  let templatesData = null;
  let connectionStatus = null;
  let currentTab = 'connection_requests';

  async function loadTemplates() {
    if (!currentLeadId || !currentContactId) return;

    try {
      const data = await api.loadTemplates(currentLeadId, currentContactId);
      templatesData = data.templates;
      connectionStatus = data.connection_status || null;
      renderTemplates();
      updateTabVisibility();
      updateConnectionStatusDisplay();
    } catch (error) {
      console.error('Error loading templates:', error);
      templatesContainer.innerHTML =
        '<p style="color: #d32f2f; padding: 20px;">Failed to load templates. Please refresh the page.</p>';
    }
  }

  function renderTemplates() {
    if (!templatesData) return;

    const categoryTemplates = templatesData[currentTab] || [];

    templatesContainer.innerHTML = '';

    if (categoryTemplates.length === 0) {
      let completionMessage = null;

      if (currentTab === 'accepted_messages' && connectionStatus?.all_followups_complete) {
        completionMessage =
          '<div style="padding: 40px 20px; text-align: center;"><div style="color: #4caf50; font-size: 48px; margin-bottom: 16px;">✓</div><h3 style="color: #111827; margin: 0 0 8px 0; font-size: 18px;">All Follow-up Messages Sent</h3><p style="color: #6b7280; margin: 0; font-size: 14px;">LinkedIn outreach complete for this contact.</p></div>';
      } else if (currentTab === 'inmail' && connectionStatus?.inmail_sent) {
        completionMessage =
          '<div style="padding: 40px 20px; text-align: center;"><div style="color: #4caf50; font-size: 48px; margin-bottom: 16px;">✓</div><h3 style="color: #111827; margin: 0 0 8px 0; font-size: 18px;">InMail Sent</h3><p style="color: #6b7280; margin: 0; font-size: 14px;">Waiting for connection acceptance to continue with follow-up messages.</p></div>';
      }

      previewContent.innerHTML =
        completionMessage ||
        '<p style="color: #666; padding: 20px;">No templates available for this category.</p>';
      copyBtn.disabled = true;
      if (markSentBtn) {
        markSentBtn.disabled = true;
        markSentBtn.style.display = 'none';
      }
      if (subjectSection) {
        subjectSection.style.display = 'none';
      }
      return;
    }

    const template = categoryTemplates[0];
    currentTemplateName = template.name;
    currentTemplateCategory = currentTab;

    updateFollowupIndicator(template);
    selectTemplate(template.name);
  }

  function updateFollowupIndicator(template) {
    if (!followupIndicator) return;

    let followupNumber = null;
    if (template && template.attempt && template.attempt.startsWith('followup_')) {
      followupNumber = template.attempt.replace('followup_', '');
    }

    if (followupNumber) {
      followupIndicator.textContent = `Follow-up ${followupNumber}`;
      followupIndicator.style.display = 'inline-block';
    } else {
      followupIndicator.style.display = 'none';
    }
  }

  async function selectTemplate(templateName) {
    if (!currentLeadId || !currentContactId) return;

    currentTemplateName = templateName;

    if (!currentTemplateCategory && templatesData) {
      for (const [category, templates] of Object.entries(templatesData)) {
        const template = templates.find((t) => t.name === templateName);
        if (template) {
          currentTemplateCategory = category;
          updateFollowupIndicator(template);
          break;
        }
      }
    }

    if (!currentTemplateCategory) {
      currentTemplateCategory = currentTab;
    }

    if (followupIndicator && followupIndicator.style.display === 'none' && templatesData) {
      for (const templates of Object.values(templatesData)) {
        const template = templates.find((t) => t.name === templateName);
        if (template) {
          updateFollowupIndicator(template);
          break;
        }
      }
    }

    document.querySelectorAll('.linkedin-template-item').forEach((item) => {
      item.classList.toggle('selected', item.dataset.templateName === templateName);
    });

    previewContent.innerHTML = '<p style="color: #666; padding: 20px;">Loading preview...</p>';
    copyBtn.disabled = true;
    if (markSentBtn) {
      markSentBtn.disabled = true;
      markSentBtn.style.display = 'none';
    }
    if (subjectSection) {
      subjectSection.style.display = 'none';
    }
    if (copySubjectBtn) {
      copySubjectBtn.disabled = true;
    }

    try {
      const profileKey = helpers.getActiveProfileKey(profileChip);
      const data = await api.loadPreview(
        currentLeadId,
        currentContactId,
        templateName,
        profileKey
      );

      if (data.has_subject && data.subject) {
        if (subjectSection) {
          subjectSection.style.display = 'block';
        }
        if (subjectContent) {
          subjectContent.textContent = data.subject;
        }
        if (copySubjectBtn) {
          copySubjectBtn.disabled = false;
        }
      } else {
        if (subjectSection) {
          subjectSection.style.display = 'none';
        }
        if (copySubjectBtn) {
          copySubjectBtn.disabled = true;
        }
      }

      const previewText = data.preview.replace(/\n/g, '<br>');
      previewContent.innerHTML = `<div style="white-space: pre-wrap; font-family: system-ui, sans-serif; line-height: 1.6; padding: 16px;">${previewText}</div>`;
      copyBtn.disabled = false;

      if (markSentBtn) {
        markSentBtn.disabled = false;
        markSentBtn.style.display = 'inline-block';
      }
    } catch (error) {
      console.error('Error loading preview:', error);
      previewContent.innerHTML = `<p style="color: #d32f2f; padding: 20px;">Failed to load preview: ${error.message}</p><p style="color: #666; font-size: 12px; margin-top: 10px;">Template: ${templateName}</p>`;
      copyBtn.disabled = true;
      if (markSentBtn) {
        markSentBtn.disabled = true;
        markSentBtn.style.display = 'none';
      }
      if (subjectSection) {
        subjectSection.style.display = 'none';
      }
      if (copySubjectBtn) {
        copySubjectBtn.disabled = true;
      }
    }
  }

  async function copyMessage() {
    if (!previewContent.textContent) return;

    try {
      const text = previewContent.innerText || previewContent.textContent;
      await navigator.clipboard.writeText(text);

      const originalText = copyBtn.textContent;
      copyBtn.textContent = 'Copied!';
      copyBtn.style.backgroundColor = '#4caf50';

      setTimeout(() => {
        copyBtn.textContent = originalText;
        copyBtn.style.backgroundColor = '';
      }, 2000);
    } catch (error) {
      console.error('Error copying:', error);
      alert('Failed to copy message. Please select and copy manually.');
    }
  }

  async function copySubject() {
    if (!subjectContent || !subjectContent.textContent) return;

    try {
      await navigator.clipboard.writeText(subjectContent.textContent);

      const originalText = copySubjectBtn.textContent;
      copySubjectBtn.textContent = 'Copied!';
      copySubjectBtn.style.backgroundColor = '#4caf50';

      setTimeout(() => {
        copySubjectBtn.textContent = originalText;
        copySubjectBtn.style.backgroundColor = '';
      }, 2000);
    } catch (error) {
      console.error('Error copying subject:', error);
      alert('Failed to copy subject. Please select and copy manually.');
    }
  }

  async function markAsSent() {
    if (!currentLeadId || !currentContactId || !currentTemplateName || !currentTemplateCategory) {
      return;
    }

    try {
      await api.markSent(
        currentLeadId,
        currentContactId,
        currentTemplateName,
        currentTemplateCategory
      );

      if (typeof showSuccess === 'function') {
        showSuccess('LinkedIn message marked as sent!');
      }

      const originalText = markSentBtn.textContent;
      markSentBtn.textContent = 'Sent!';
      markSentBtn.style.backgroundColor = '#4caf50';
      markSentBtn.disabled = true;

      setTimeout(() => {
        if (modal) {
          modal.style.display = 'none';
        }
      }, 1500);
    } catch (error) {
      console.error('Error marking as sent:', error);
      alert(`Failed to mark message as sent: ${error.message}`);
    }
  }

  function updateConnectionStatusDisplay() {
    if (!connectionStatusContainer || !connectionStatus) return;

    const { is_connected, has_connection_request } = connectionStatus;

    if (is_connected) {
      connectionStatusContainer.style.display = 'flex';
      connectionStatusText.textContent = '✓ Connection Accepted';
      connectionStatusText.style.color = '#4caf50';
      markConnectionAcceptedBtn.style.display = 'none';
    } else if (has_connection_request) {
      connectionStatusContainer.style.display = 'flex';
      connectionStatusText.textContent = '⏳ Connection Request Pending';
      connectionStatusText.style.color = '#ff9800';
      markConnectionAcceptedBtn.style.display = 'inline-block';
      markConnectionAcceptedBtn.textContent = 'Mark as Accepted';
      markConnectionAcceptedBtn.style.backgroundColor = '';
      markConnectionAcceptedBtn.style.color = '';
      markConnectionAcceptedBtn.disabled = false;
    } else {
      connectionStatusContainer.style.display = 'none';
    }
  }

  async function markConnectionAccepted() {
    if (!currentLeadId || !currentContactId) return;

    const isCurrentlyAccepted = connectionStatus?.is_connected || false;
    if (isCurrentlyAccepted) {
      return;
    }

    try {
      const originalText = markConnectionAcceptedBtn.textContent;
      markConnectionAcceptedBtn.disabled = true;
      markConnectionAcceptedBtn.textContent = 'Processing...';

      await api.markConnectionAccepted(currentLeadId, currentContactId);

      markConnectionAcceptedBtn.textContent = '✓ Accepted';
      markConnectionAcceptedBtn.style.backgroundColor = '#4caf50';
      markConnectionAcceptedBtn.style.color = '#ffffff';
      markConnectionAcceptedBtn.disabled = false;

      await loadTemplates();

      setTimeout(() => {
        if (markConnectionAcceptedBtn.style.display !== 'none') {
          markConnectionAcceptedBtn.textContent = originalText;
          markConnectionAcceptedBtn.style.backgroundColor = '';
          markConnectionAcceptedBtn.style.color = '';
        }
      }, 2000);
    } catch (error) {
      console.error('Error marking connection as accepted:', error);

      const originalText = markConnectionAcceptedBtn.textContent;
      markConnectionAcceptedBtn.textContent = 'Error - Try Again';
      markConnectionAcceptedBtn.style.backgroundColor = '#f44336';
      markConnectionAcceptedBtn.style.color = '#ffffff';
      markConnectionAcceptedBtn.disabled = false;

      setTimeout(() => {
        markConnectionAcceptedBtn.textContent = originalText;
        markConnectionAcceptedBtn.style.backgroundColor = '';
        markConnectionAcceptedBtn.style.color = '';
      }, 3000);
    }
  }

  function updateTabVisibility() {
    if (!connectionStatus) return;

    tabs.forEach((tab) => {
      const tabName = tab.dataset.tab;
      let shouldShow = true;

      if (tabName === 'connection_requests') {
        shouldShow = connectionStatus.can_send_connection;
      } else if (tabName === 'accepted_messages') {
        shouldShow = connectionStatus.can_send_messages;
      } else if (tabName === 'inmail') {
        shouldShow = connectionStatus.can_send_inmail;
      }

      if (shouldShow) {
        tab.style.display = 'inline-block';
      } else {
        tab.style.display = 'none';
        if (tab.classList.contains('active')) {
          const firstVisible = Array.from(tabs).find((t) => t.style.display !== 'none');
          if (firstVisible) {
            switchTab(firstVisible.dataset.tab);
          }
        }
      }
    });
  }

  function switchTab(tabName) {
    currentTab = tabName;
    currentTemplateName = null;
    currentTemplateCategory = null;

    if (followupIndicator) {
      followupIndicator.style.display = 'none';
    }

    tabs.forEach((tab) => {
      tab.classList.toggle('active', tab.dataset.tab === tabName);
    });

    previewContent.innerHTML =
      '<p style="color: #999; padding: 20px; text-align: center;">Loading...</p>';
    copyBtn.disabled = true;
    if (markSentBtn) {
      markSentBtn.disabled = true;
      markSentBtn.style.display = 'none';
    }

    renderTemplates();
  }

  function openModal(leadId, contactId) {
    currentLeadId = leadId;
    currentContactId = contactId;
    currentTemplateName = null;
    currentTab = 'connection_requests';

    helpers.updateProfileLabel(profileLabel, profileChip);
    modal.style.display = 'flex';
    loadTemplates();

    tabs.forEach((tab) => {
      tab.classList.toggle('active', tab.dataset.tab === 'connection_requests');
    });
  }

  function closeModal() {
    modal.style.display = 'none';
    currentLeadId = null;
    currentContactId = null;
    currentTemplateName = null;
    previewContent.innerHTML =
      '<p style="color: #999; padding: 20px; text-align: center;">Select a template to preview</p>';
    copyBtn.disabled = true;
    if (subjectSection) {
      subjectSection.style.display = 'none';
    }
    if (copySubjectBtn) {
      copySubjectBtn.disabled = true;
    }
  }

  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.linkedin-messages-btn');
    if (!btn) return;

    e.preventDefault();
    const leadId = btn.dataset.leadId;
    const contactId = btn.dataset.contactId;

    if (!leadId) {
      alert('Lead ID not found');
      return;
    }

    if (!contactId) {
      alert('Contact ID not found');
      return;
    }

    openModal(leadId, contactId);
  });

  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      switchTab(tab.dataset.tab);
    });
  });

  if (copyBtn) {
    copyBtn.addEventListener('click', copyMessage);
  }

  if (copySubjectBtn) {
    copySubjectBtn.addEventListener('click', copySubject);
  }

  if (markSentBtn) {
    markSentBtn.addEventListener('click', markAsSent);
  }

  if (markConnectionAcceptedBtn) {
    markConnectionAcceptedBtn.addEventListener('click', markConnectionAccepted);
  }

  closeButtons.forEach((btn) => {
    btn.addEventListener('click', closeModal);
  });

  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        closeModal();
      }
    });
  }

  const observer = new MutationObserver(() => {
    if (modal.style.display !== 'none') {
      helpers.updateProfileLabel(profileLabel, profileChip);
      if (currentTemplateName) {
        selectTemplate(currentTemplateName);
      }
    }
  });

  if (profileChip) {
    observer.observe(profileChip, { childList: true, subtree: true });
  }
})();
