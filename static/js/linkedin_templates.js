/**
 * LinkedIn message templates modal functionality.
 */

(function() {
  'use strict';

  const modal = document.getElementById('linkedin-modal');
  const templatesContainer = document.getElementById('linkedin-templates-container');
  const previewContent = document.getElementById('linkedin-preview-content');
  const copyBtn = document.getElementById('linkedin-copy-btn');
  const markSentBtn = document.getElementById('linkedin-mark-sent-btn');
  const followupIndicator = document.getElementById('linkedin-followup-indicator');
  const profileLabel = document.getElementById('linkedin-profile-label');
  const tabs = document.querySelectorAll('.linkedin-tab');
  const closeButtons = document.querySelectorAll('#linkedin-modal .modal-close');

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
    const contentDiv = document.querySelector('.linkedin-content');
    
    // For inmail and connection_requests, always use single-template layout
    const isSingleTemplateTab = currentTab === 'inmail' || currentTab === 'connection_requests';
    
    if (categoryTemplates.length === 0) {
      // For inmail and connection_requests, still use single-template layout even if empty
      if (isSingleTemplateTab && contentDiv) {
        contentDiv.classList.add('single-template');
        templatesContainer.innerHTML = '';
        previewContent.innerHTML = '<p style="color: #666; padding: 20px;">No templates available for this category.</p>';
        copyBtn.disabled = true;
        if (markSentBtn) {
          markSentBtn.disabled = true;
          markSentBtn.style.display = 'none';
        }
        return;
      }
      templatesContainer.innerHTML = '<p style="color: #666; padding: 20px;">No templates in this category.</p>';
      if (contentDiv) contentDiv.classList.remove('single-template');
      return;
    }

    // For tabs with only one template (connection_requests, inmail), hide list and auto-load
    // Also treat inmail and connection_requests as single-template tabs even if multiple exist
    const isSingleTemplate = categoryTemplates.length === 1 || isSingleTemplateTab;
    
    if (isSingleTemplate) {
      // Hide template list and show full-width preview
      if (contentDiv) {
        contentDiv.classList.add('single-template');
      }
      templatesContainer.innerHTML = '';
      
      // Auto-select and load the first template (or only template)
      const template = categoryTemplates[0];
      currentTemplateName = template.name;
      currentTemplateCategory = currentTab; // Set category before loading
      
      // Show follow-up indicator if applicable
      updateFollowupIndicator(template);
      
      selectTemplate(template.name);
      return;
    }

    // For multiple templates (accepted_messages), show list
    if (contentDiv) {
      contentDiv.classList.remove('single-template');
    }

    const html = categoryTemplates.map(template => {
      const isSelected = currentTemplateName === template.name;
      
      // Extract follow-up number from attempt field (e.g., "followup_1" -> "1")
      let followupNumber = null;
      if (template.attempt && template.attempt.startsWith('followup_')) {
        followupNumber = template.attempt.replace('followup_', '');
      }
      
      return `
        <div class="linkedin-template-item ${isSelected ? 'selected' : ''}" 
             data-template-name="${template.name}"
             data-template-display="${template.display_name}">
          <div class="linkedin-template-name">
            ${template.display_name}
            ${followupNumber ? `<span class="linkedin-followup-badge">Follow-up ${followupNumber}</span>` : ''}
          </div>
        </div>
      `;
    }).join('');

    templatesContainer.innerHTML = html;

    // Attach click handlers
    document.querySelectorAll('.linkedin-template-item').forEach(item => {
      item.addEventListener('click', () => {
        const templateName = item.dataset.templateName;
        selectTemplate(templateName);
      });
    });
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

  // Mark as Sent button
  if (markSentBtn) {
    markSentBtn.addEventListener('click', markAsSent);
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

