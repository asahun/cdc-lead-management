/**
 * LinkedIn message templates modal functionality.
 */

(function() {
  'use strict';

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

  let currentLeadId = null;
  let currentContactId = null;
  let currentTemplateName = null;
  let currentTemplateCategory = null;
  let templatesData = null;
  let connectionStatus = null;
  let currentTab = 'connection_requests';

  /**
   * Get active profile key (same as email compose)
   */
  function getActiveProfileKey() {
    const profileChip = document.querySelector('[data-profile-label]');
    if (profileChip) {
      const profileText = profileChip.textContent.trim().toLowerCase();
      return profileText === 'fisseha' ? 'fisseha' : 'abby';
    }
    return 'abby';
  }

  /**
   * Update profile label
   */
  function updateProfileLabel() {
    const profileKey = getActiveProfileKey();
    const profileChip = document.querySelector('[data-profile-label]');
    if (profileChip && profileLabel) {
      profileLabel.textContent = profileChip.textContent.trim();
    }
  }

  /**
   * Load templates from backend
   */
  async function loadTemplates() {
    if (!currentLeadId || !currentContactId) return;

    try {
      const response = await fetch(`/leads/${currentLeadId}/linkedin-templates?contact_id=${currentContactId}`);
      if (!response.ok) {
        throw new Error('Failed to load templates');
      }
      const data = await response.json();
      templatesData = data.templates;
      connectionStatus = data.connection_status || null;
      renderTemplates();
      updateTabVisibility();
      updateConnectionStatusDisplay();
    } catch (error) {
      console.error('Error loading templates:', error);
      templatesContainer.innerHTML = '<p style="color: #d32f2f; padding: 20px;">Failed to load templates. Please refresh the page.</p>';
    }
  }

  /**
   * Render templates for current tab
   */
  function renderTemplates() {
    if (!templatesData) return;

    const categoryTemplates = templatesData[currentTab] || [];
    
    // Always hide template list (we auto-load single templates)
    templatesContainer.innerHTML = '';
    
    if (categoryTemplates.length === 0) {
      // Show completion messages when appropriate
      let completionMessage = null;
      
      if (currentTab === 'accepted_messages' && connectionStatus?.all_followups_complete) {
        completionMessage = '<div style="padding: 40px 20px; text-align: center;"><div style="color: #4caf50; font-size: 48px; margin-bottom: 16px;">✓</div><h3 style="color: #111827; margin: 0 0 8px 0; font-size: 18px;">All Follow-up Messages Sent</h3><p style="color: #6b7280; margin: 0; font-size: 14px;">LinkedIn outreach complete for this contact.</p></div>';
      } else if (currentTab === 'inmail' && connectionStatus?.inmail_sent) {
        completionMessage = '<div style="padding: 40px 20px; text-align: center;"><div style="color: #4caf50; font-size: 48px; margin-bottom: 16px;">✓</div><h3 style="color: #111827; margin: 0 0 8px 0; font-size: 18px;">InMail Sent</h3><p style="color: #6b7280; margin: 0; font-size: 14px;">Waiting for connection acceptance to continue with follow-up messages.</p></div>';
      }
      
      previewContent.innerHTML = completionMessage || '<p style="color: #666; padding: 20px;">No templates available for this category.</p>';
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

    // Auto-load the first (and only) template
    const template = categoryTemplates[0];
    currentTemplateName = template.name;
    currentTemplateCategory = currentTab;
    
    // Show follow-up indicator if applicable
    updateFollowupIndicator(template);
    
    // Load template preview
    selectTemplate(template.name);
  }

  /**
   * Update follow-up indicator badge
   */
  function updateFollowupIndicator(template) {
    if (!followupIndicator) return;
    
    // Extract follow-up number from attempt field
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

  /**
   * Select a template and load preview
   */
  async function selectTemplate(templateName) {
    if (!currentLeadId || !currentContactId) return;

    currentTemplateName = templateName;
    
    // Find template category if not already set
    if (!currentTemplateCategory && templatesData) {
      for (const [category, templates] of Object.entries(templatesData)) {
        const template = templates.find(t => t.name === templateName);
        if (template) {
          currentTemplateCategory = category;
          // Update follow-up indicator
          updateFollowupIndicator(template);
          break;
        }
      }
    }
    
    // Fallback: use current tab as category if still not set
    if (!currentTemplateCategory) {
      currentTemplateCategory = currentTab;
    }
    
    // If we haven't updated the indicator yet, find the template and update it
    if (followupIndicator && followupIndicator.style.display === 'none' && templatesData) {
      for (const templates of Object.values(templatesData)) {
        const template = templates.find(t => t.name === templateName);
        if (template) {
          updateFollowupIndicator(template);
          break;
        }
      }
    }
    
    // Update UI (only if template list is visible)
    document.querySelectorAll('.linkedin-template-item').forEach(item => {
      item.classList.toggle('selected', item.dataset.templateName === templateName);
    });

    // Show loading
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
      const profileKey = getActiveProfileKey();
      const response = await fetch(
        `/leads/${currentLeadId}/contacts/${currentContactId}/linkedin-preview?template_name=${encodeURIComponent(templateName)}&profile=${encodeURIComponent(profileKey)}`
      );
      
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to load preview');
      }

      const data = await response.json();
      
      // Handle subject line for InMail templates
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
      
      // Render preview (preserve line breaks)
      const previewText = data.preview.replace(/\n/g, '<br>');
      previewContent.innerHTML = `<div style="white-space: pre-wrap; font-family: system-ui, sans-serif; line-height: 1.6; padding: 16px;">${previewText}</div>`;
      copyBtn.disabled = false;
      
      // Show "Mark as Sent" button
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

  /**
   * Copy message to clipboard
   */
  async function copyMessage() {
    if (!previewContent.textContent) return;

    try {
      // Get plain text (remove HTML)
      const text = previewContent.innerText || previewContent.textContent;
      await navigator.clipboard.writeText(text);
      
      // Show success feedback
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

  /**
   * Copy subject line to clipboard
   */
  async function copySubject() {
    if (!subjectContent || !subjectContent.textContent) return;

    try {
      await navigator.clipboard.writeText(subjectContent.textContent);
      
      // Show success feedback
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

  /**
   * Mark LinkedIn message as sent
   */
  async function markAsSent() {
    if (!currentLeadId || !currentContactId || !currentTemplateName || !currentTemplateCategory) return;

    try {
      const formData = new FormData();
      formData.append('template_name', currentTemplateName);
      formData.append('template_category', currentTemplateCategory);

      const response = await fetch(
        `/leads/${currentLeadId}/contacts/${currentContactId}/linkedin-mark-sent`,
        {
          method: 'POST',
          body: formData
        }
      );

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to mark message as sent');
      }

      const data = await response.json();
      
      // Show success feedback
      const originalText = markSentBtn.textContent;
      markSentBtn.textContent = 'Sent!';
      markSentBtn.style.backgroundColor = '#4caf50';
      markSentBtn.disabled = true;
      
      // Reload templates to update UI state
      await loadTemplates();
      
      setTimeout(() => {
        markSentBtn.textContent = originalText;
        markSentBtn.style.backgroundColor = '';
        markSentBtn.style.display = 'none';
      }, 2000);
    } catch (error) {
      console.error('Error marking as sent:', error);
      alert(`Failed to mark message as sent: ${error.message}`);
    }
  }

  /**
   * Update connection status display
   */
  function updateConnectionStatusDisplay() {
    if (!connectionStatusContainer || !connectionStatus) return;

    const { is_connected, has_connection_request } = connectionStatus;

    if (is_connected) {
      // Connection is accepted - show success status
      connectionStatusContainer.style.display = 'flex';
      connectionStatusText.textContent = '✓ Connection Accepted';
      connectionStatusText.style.color = '#4caf50';
      // Hide the button since connection is already accepted
      markConnectionAcceptedBtn.style.display = 'none';
    } else if (has_connection_request) {
      // Connection request sent but not yet accepted - show pending status with toggle button
      connectionStatusContainer.style.display = 'flex';
      connectionStatusText.textContent = '⏳ Connection Request Pending';
      connectionStatusText.style.color = '#ff9800';
      markConnectionAcceptedBtn.style.display = 'inline-block';
      // Reset button to default state
      markConnectionAcceptedBtn.textContent = 'Mark as Accepted';
      markConnectionAcceptedBtn.style.backgroundColor = '';
      markConnectionAcceptedBtn.style.color = '';
      markConnectionAcceptedBtn.disabled = false;
    } else {
      // No connection request sent yet
      connectionStatusContainer.style.display = 'none';
    }
  }

  /**
   * Mark connection as accepted (no confirmation popup - immediate action with visual feedback)
   */
  async function markConnectionAccepted() {
    if (!currentLeadId || !currentContactId) return;

    // Check current state - if already accepted, don't do anything
    const isCurrentlyAccepted = connectionStatus?.is_connected || false;
    if (isCurrentlyAccepted) {
      return;
    }

    try {
      // Disable button during request
      const originalText = markConnectionAcceptedBtn.textContent;
      markConnectionAcceptedBtn.disabled = true;
      markConnectionAcceptedBtn.textContent = 'Processing...';

      const response = await fetch(
        `/leads/${currentLeadId}/contacts/${currentContactId}/linkedin-connection-accepted`,
        {
          method: 'POST'
        }
      );

      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail || 'Failed to mark connection as accepted');
      }

      const data = await response.json();
      
      // Show success feedback - green flash
      markConnectionAcceptedBtn.textContent = '✓ Accepted';
      markConnectionAcceptedBtn.style.backgroundColor = '#4caf50';
      markConnectionAcceptedBtn.style.color = '#ffffff';
      markConnectionAcceptedBtn.disabled = false;
      
      // Reload templates to update UI state (this will update connectionStatus)
      await loadTemplates();
      
      // The updateConnectionStatusDisplay will hide the button after reload
      // But keep the green state for a moment for visual feedback
      setTimeout(() => {
        // Button will be hidden by updateConnectionStatusDisplay if connected
        // If still visible, reset to normal state
        if (markConnectionAcceptedBtn.style.display !== 'none') {
          markConnectionAcceptedBtn.textContent = originalText;
          markConnectionAcceptedBtn.style.backgroundColor = '';
          markConnectionAcceptedBtn.style.color = '';
        }
      }, 2000);
    } catch (error) {
      console.error('Error marking connection as accepted:', error);
      
      // Show inline error instead of alert
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

  /**
   * Update tab visibility based on connection status
   */
  function updateTabVisibility() {
    if (!connectionStatus) return;

    tabs.forEach(tab => {
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
        // If current tab is hidden, switch to first visible tab
        if (tab.classList.contains('active')) {
          const firstVisible = Array.from(tabs).find(t => t.style.display !== 'none');
          if (firstVisible) {
            switchTab(firstVisible.dataset.tab);
          }
        }
      }
    });
  }

  /**
   * Handle tab switching
   */
  function switchTab(tabName) {
    currentTab = tabName;
    currentTemplateName = null;
    currentTemplateCategory = null; // Reset category when switching tabs
    
    // Hide follow-up indicator when switching tabs
    if (followupIndicator) {
      followupIndicator.style.display = 'none';
    }
    
    // Update tab buttons
    tabs.forEach(tab => {
      tab.classList.toggle('active', tab.dataset.tab === tabName);
    });

    // Clear preview (will be auto-loaded if single template)
    previewContent.innerHTML = '<p style="color: #999; padding: 20px; text-align: center;">Loading...</p>';
    copyBtn.disabled = true;
    if (markSentBtn) {
      markSentBtn.disabled = true;
      markSentBtn.style.display = 'none';
    }

    // Render templates for new tab (will auto-load if single template)
    renderTemplates();
  }

  /**
   * Open modal
   */
  function openModal(leadId, contactId) {
    currentLeadId = leadId;
    currentContactId = contactId;
    currentTemplateName = null;
    currentTab = 'connection_requests';

    updateProfileLabel();
    modal.style.display = 'flex';
    loadTemplates();

    // Reset tabs
    tabs.forEach(tab => {
      tab.classList.toggle('active', tab.dataset.tab === 'connection_requests');
    });
  }

  /**
   * Close modal
   */
  function closeModal() {
    modal.style.display = 'none';
    currentLeadId = null;
    currentContactId = null;
    currentTemplateName = null;
    previewContent.innerHTML = '<p style="color: #999; padding: 20px; text-align: center;">Select a template to preview</p>';
    copyBtn.disabled = true;
    if (subjectSection) {
      subjectSection.style.display = 'none';
    }
    if (copySubjectBtn) {
      copySubjectBtn.disabled = true;
    }
  }

  // Event listeners
  document.addEventListener('click', (e) => {
    const btn = e.target.closest('.linkedin-messages-btn');
    if (btn) {
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
    }
  });

  // Tab switching
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      switchTab(tab.dataset.tab);
    });
  });

  // Copy button
  if (copyBtn) {
    copyBtn.addEventListener('click', copyMessage);
  }

  // Copy Subject button
  if (copySubjectBtn) {
    copySubjectBtn.addEventListener('click', copySubject);
  }

  // Mark as Sent button
  if (markSentBtn) {
    markSentBtn.addEventListener('click', markAsSent);
  }

  // Mark Connection Accepted button
  if (markConnectionAcceptedBtn) {
    markConnectionAcceptedBtn.addEventListener('click', markConnectionAccepted);
  }

  // Close buttons
  closeButtons.forEach(btn => {
    btn.addEventListener('click', closeModal);
  });

  // Close on outside click
  if (modal) {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) {
        closeModal();
      }
    });
  }

  // Update profile label when email profile changes (if on same page)
  const observer = new MutationObserver(() => {
    if (modal.style.display !== 'none') {
      updateProfileLabel();
      // Reload preview if template is selected
      if (currentTemplateName) {
        selectTemplate(currentTemplateName);
      }
    }
  });

  const profileChip = document.querySelector('[data-profile-label]');
  if (profileChip) {
    observer.observe(profileChip, { childList: true, subtree: true });
  }
})();

