(function () {
  'use strict';

  const helpers = window.JourneyDisplay?.helpers;
  if (!helpers) return;

  function renderJourney(container, data) {
    const startedAt = new Date(data.started_at);
    const daysElapsed = data.days_elapsed;

    const primaryContactInfo = data.primary_contact
      ? `<span class="journey-primary-contact">Primary Contact: ${data.primary_contact.name}${
          data.primary_contact.title ? ` (${data.primary_contact.title})` : ''
        }</span>`
      : '';

    const html = `
      <div class="journey-header">
        <div class="journey-meta">
          ${primaryContactInfo}
          <span class="journey-started">Started: ${helpers.formatDate(startedAt)}</span>
          <span class="journey-days">Day ${daysElapsed} of 42</span>
        </div>
      </div>
      <div class="journey-channels">
        ${renderChannel('email', '📧', 'Email Journey', data.email)}
        ${renderChannel('linkedin', '💼', 'LinkedIn Journey', data.linkedin)}
        ${renderChannel('mail', '📮', 'Mail Journey', data.mail)}
      </div>
    `;

    container.innerHTML = html;
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

    const completedCount = milestones.filter((m) => m.status === 'completed').length;
    const totalCount = milestones.length;
    const progressPercent = totalCount > 0 ? Math.round((completedCount / totalCount) * 100) : 0;

    const milestonesHtml = milestones.map((milestone) => renderMilestone(milestone)).join('');

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
    const statusIcon = helpers.getStatusIcon(status);
    const expectedDate = new Date(milestone.expected_date);
    const isOverdue = status === 'overdue';
    const isCompleted = status === 'completed';

    let dateInfo = '';
    if (isCompleted && milestone.completed_at) {
      const completedDate = new Date(milestone.completed_at);
      dateInfo = `<span class="milestone-date completed">Completed ${helpers.formatDate(completedDate)}</span>`;
    } else if (isOverdue) {
      dateInfo = `<span class="milestone-date overdue">Overdue since ${helpers.formatDate(expectedDate)}</span>`;
    } else {
      dateInfo = `<span class="milestone-date">Due ${helpers.formatDate(expectedDate)}</span>`;
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

  window.JourneyDisplay = window.JourneyDisplay || {};
  window.JourneyDisplay.render = {
    renderJourney,
  };
})();
