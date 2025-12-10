/**
 * Journey Display Component
 * Shows delivery-style journey tracking for leads in 'ready' status
 */

(function() {
  'use strict';

  const journeyDisplay = document.getElementById('journey-display');
  if (!journeyDisplay) return;

  // Get lead status from parent section
  const journeySection = journeyDisplay.closest('#journey-tracking');
  const leadStatus = journeySection?.dataset.leadStatus || '';
  const isResponseReceived = leadStatus === 'response_received';
  
  // Set initial collapsed state based on status
  let isCollapsed = isResponseReceived; // collapsed for response_received, expanded for others
  
  const toggleButton = document.getElementById('journey-toggle');
  const goalMessage = document.getElementById('journey-goal-message');

  function applyCollapsedState() {
    if (!journeySection) return;
    
    if (isCollapsed) {
      journeySection.classList.add('collapsed');
    } else {
      journeySection.classList.remove('collapsed');
    }
    
    // Show goal message only when collapsed AND status is response_received
    if (goalMessage) {
      if (isCollapsed && isResponseReceived) {
        goalMessage.classList.add('show');
      } else {
        goalMessage.classList.remove('show');
      }
    }
    
    if (toggleButton) {
      toggleButton.textContent = isCollapsed ? 'Show Journey' : 'Hide Journey';
      toggleButton.setAttribute('aria-expanded', String(!isCollapsed));
    }
  }

  // Initialize collapsed state
  applyCollapsedState();

  // Handle toggle click
  toggleButton?.addEventListener('click', () => {
    isCollapsed = !isCollapsed;
    applyCollapsedState();
  });

  const leadId = journeyDisplay.dataset.leadId;
  const journeyDataStr = journeyDisplay.dataset.journeyData;
  
  let journeyData = null;
  try {
    journeyData = journeyDataStr && journeyDataStr !== 'null' ? JSON.parse(journeyDataStr) : null;
  } catch (e) {
    console.error('Failed to parse journey data:', e);
  }

  if (!journeyData) {
    // Try to fetch from API
    fetch(`/api/leads/${leadId}/journey`)
      .then(res => res.json())
      .then(data => {
        if (data.error) {
          journeyDisplay.innerHTML = `<div class="journey-error">${data.error}</div>`;
          return;
        }
        renderJourney(data);
        // Re-apply collapsed state after rendering
        applyCollapsedState();
      })
      .catch(err => {
        console.error('Failed to fetch journey data:', err);
        journeyDisplay.innerHTML = '<div class="journey-error">Failed to load journey data</div>';
        // Re-apply collapsed state after error
        applyCollapsedState();
      });
  } else {
    renderJourney(journeyData);
    // Re-apply collapsed state after rendering
    applyCollapsedState();
  }

  function renderJourney(data) {
    const now = new Date();
    const startedAt = new Date(data.started_at);
    const daysElapsed = data.days_elapsed;
    
    const primaryContactInfo = data.primary_contact 
      ? `<span class="journey-primary-contact">Primary Contact: ${data.primary_contact.name}${data.primary_contact.title ? ` (${data.primary_contact.title})` : ''}</span>`
      : '';

    let html = `
      <div class="journey-header">
        <div class="journey-meta">
          ${primaryContactInfo}
          <span class="journey-started">Started: ${formatDate(startedAt)}</span>
          <span class="journey-days">Day ${daysElapsed} of 42</span>
        </div>
      </div>
      <div class="journey-channels">
        ${renderChannel('email', '📧', 'Email Journey', data.email)}
        ${renderChannel('linkedin', '💼', 'LinkedIn Journey', data.linkedin)}
        ${renderChannel('mail', '📮', 'Mail Journey', data.mail)}
      </div>
    `;

    journeyDisplay.innerHTML = html;
  }

  function renderChannel(channelName, icon, title, milestones) {
    if (!milestones || milestones.length === 0) {
      return `
        <div class="journey-channel journey-channel-${channelName}">
          <div class="channel-header">
            <span class="channel-icon">${icon}</span>
            <h3 class="channel-title">${title}</h3>
          </div>
          <div class="channel-milestones">
            <p class="no-milestones">No milestones defined</p>
          </div>
        </div>
      `;
    }

    const completedCount = milestones.filter(m => m.status === 'completed').length;
    const totalCount = milestones.length;
    const progressPercent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

    let milestonesHtml = milestones.map(milestone => {
      return renderMilestone(milestone);
    }).join('');

    return `
      <div class="journey-channel journey-channel-${channelName}">
        <div class="channel-header">
          <span class="channel-icon">${icon}</span>
          <h3 class="channel-title">${title}</h3>
          <span class="channel-progress">${completedCount}/${totalCount} (${progressPercent}%)</span>
        </div>
        <div class="channel-milestones">
          ${milestonesHtml}
        </div>
      </div>
    `;
  }

  function renderMilestone(milestone) {
    const status = milestone.status;
    const statusClass = `milestone-${status}`;
    const statusIcon = getStatusIcon(status);
    const expectedDate = new Date(milestone.expected_date);
    const isOverdue = status === 'overdue';
    const isCompleted = status === 'completed';
    const isSkipped = status === 'skipped';
    
    let dateInfo = '';
    if (isCompleted && milestone.completed_at) {
      const completedDate = new Date(milestone.completed_at);
      dateInfo = `<span class="milestone-date completed">Completed ${formatDate(completedDate)}</span>`;
    } else if (isOverdue) {
      dateInfo = `<span class="milestone-date overdue">Overdue since ${formatDate(expectedDate)}</span>`;
    } else {
      dateInfo = `<span class="milestone-date">Due ${formatDate(expectedDate)}</span>`;
    }

    let attemptLink = '';
    if (milestone.attempt_id) {
      attemptLink = `<a href="#attempts" class="milestone-link" title="View attempt">View Attempt</a>`;
    }

    return `
      <div class="journey-milestone ${statusClass}">
        <div class="milestone-status-icon">${statusIcon}</div>
        <div class="milestone-content">
          <div class="milestone-label">${milestone.label}</div>
          <div class="milestone-meta">
            ${dateInfo}
            ${attemptLink}
          </div>
        </div>
      </div>
    `;
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

  function formatDate(date) {
    if (!(date instanceof Date)) {
      date = new Date(date);
    }
    return date.toLocaleDateString('en-US', { 
      month: 'short', 
      day: 'numeric', 
      year: 'numeric' 
    });
  }
})();

