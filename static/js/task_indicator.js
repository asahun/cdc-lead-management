/**
 * Task Indicator for Leads List
 * Shows bell icons with color coding and popup with task details
 */

(function() {
  'use strict';

  const taskBells = document.querySelectorAll('.task-bell');
  const taskPopup = document.getElementById('task-popup');
  const taskPopupContent = document.getElementById('task-popup-content');
  const taskPopupLoading = document.getElementById('task-popup-loading');
  const taskPopupClose = document.querySelector('.task-popup-close');
  let currentLeadId = null;
  let journeyStatusCache = {};

  // Load journey statuses for all visible leads on page load
  function loadJourneyStatuses() {
    const leadIds = Array.from(taskBells).map(bell => bell.dataset.leadId);
    if (leadIds.length === 0) return;

    fetch('/api/leads/batch/journey-status', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ lead_ids: leadIds }),
    })
      .then(res => res.json())
      .then(data => {
        journeyStatusCache = data;
        updateBellIcons();
      })
      .catch(err => {
        console.error('Failed to load journey statuses:', err);
      });
  }

  // Update bell icon colors based on priority
  function updateBellIcons() {
    taskBells.forEach(bell => {
      const leadId = bell.dataset.leadId;
      const status = journeyStatusCache[leadId];
      
      if (!status) {
        bell.classList.remove('bell-overdue', 'bell-due-soon', 'bell-upcoming');
        return;
      }

      // Remove all color classes
      bell.classList.remove('bell-overdue', 'bell-due-soon', 'bell-upcoming');
      
      // Add appropriate color class
      if (status.priority === 'overdue') {
        bell.classList.add('bell-overdue');
      } else if (status.priority === 'due_soon') {
        bell.classList.add('bell-due-soon');
      } else if (status.priority === 'upcoming') {
        bell.classList.add('bell-upcoming');
      }
    });
  }

  // Show popup with task details
  function showTaskPopup(leadId) {
    currentLeadId = leadId;
    taskPopup.style.display = 'flex';
    taskPopupContent.style.display = 'none';
    taskPopupLoading.style.display = 'block';

    // Check cache first
    const cachedStatus = journeyStatusCache[leadId];
    if (cachedStatus) {
      renderTaskPopup(cachedStatus);
      return;
    }

    // Fetch individual status if not in cache
    fetch(`/api/leads/${leadId}/journey`)
      .then(res => res.json())
      .then(journeyData => {
        // Convert full journey data to summary format
        const summary = convertJourneyToSummary(journeyData);
        journeyStatusCache[leadId] = summary;
        renderTaskPopup(summary);
      })
      .catch(err => {
        console.error('Failed to load task details:', err);
        taskPopupLoading.textContent = 'Failed to load tasks';
      });
  }

  // Convert full journey data to summary format
  function convertJourneyToSummary(journeyData) {
    const now = new Date();
    const startedAt = new Date(journeyData.started_at);
    
    const overdue = [];
    const dueSoon = [];
    const upcoming = [];
    
    const channelIcons = {
      email: '📧',
      linkedin: '💼',
      mail: '📮',
    };
    
    // Process all milestones
    const allMilestones = [
      ...journeyData.email,
      ...journeyData.linkedin,
      ...journeyData.mail,
    ];
    
    allMilestones.forEach(milestone => {
      if (milestone.status === 'completed' || milestone.status === 'skipped') {
        return;
      }
      
      const expectedDate = new Date(milestone.expected_date);
      const daysUntil = Math.ceil((expectedDate - now) / (1000 * 60 * 60 * 24));
      
      const taskData = {
        label: milestone.label,
        channel: milestone.channel,
        channel_icon: channelIcons[milestone.channel] || '•',
        expected_date: milestone.expected_date,
        days_until: daysUntil,
      };
      
      if (milestone.status === 'overdue' || daysUntil < 0) {
        overdue.push(taskData);
      } else if (daysUntil <= 2) {
        dueSoon.push(taskData);
      } else if (daysUntil <= 7) {
        upcoming.push(taskData);
      }
    });
    
    const priority = overdue.length > 0 ? 'overdue' :
                     dueSoon.length > 0 ? 'due_soon' :
                     upcoming.length > 0 ? 'upcoming' : 'none';
    
    return {
      priority,
      overdue_count: overdue.length,
      due_soon_count: dueSoon.length,
      upcoming_count: upcoming.length,
      overdue,
      due_soon: dueSoon,
      upcoming,
    };
  }

  // Render task popup content
  function renderTaskPopup(status) {
    taskPopupLoading.style.display = 'none';
    taskPopupContent.style.display = 'block';
    
    // Clear previous content
    document.getElementById('task-overdue-list').innerHTML = '';
    document.getElementById('task-due-soon-list').innerHTML = '';
    document.getElementById('task-upcoming-list').innerHTML = '';
    
    // Show/hide sections
    const overdueSection = document.getElementById('task-overdue-section');
    const dueSoonSection = document.getElementById('task-due-soon-section');
    const upcomingSection = document.getElementById('task-upcoming-section');
    const emptySection = document.getElementById('task-empty');
    
    if (status.overdue.length > 0) {
      overdueSection.style.display = 'block';
      status.overdue.forEach(task => {
        const li = createTaskListItem(task, 'overdue');
        document.getElementById('task-overdue-list').appendChild(li);
      });
    } else {
      overdueSection.style.display = 'none';
    }
    
    if (status.due_soon.length > 0) {
      dueSoonSection.style.display = 'block';
      status.due_soon.forEach(task => {
        const li = createTaskListItem(task, 'due-soon');
        document.getElementById('task-due-soon-list').appendChild(li);
      });
    } else {
      dueSoonSection.style.display = 'none';
    }
    
    if (status.upcoming.length > 0) {
      upcomingSection.style.display = 'block';
      status.upcoming.forEach(task => {
        const li = createTaskListItem(task, 'upcoming');
        document.getElementById('task-upcoming-list').appendChild(li);
      });
    } else {
      upcomingSection.style.display = 'none';
    }
    
    // Show empty message if no tasks
    if (status.overdue.length === 0 && status.due_soon.length === 0 && status.upcoming.length === 0) {
      emptySection.style.display = 'block';
    } else {
      emptySection.style.display = 'none';
    }
  }

  // Create a task list item
  function createTaskListItem(task, category) {
    const li = document.createElement('li');
    li.className = `task-item task-item-${category}`;
    
    const expectedDate = new Date(task.expected_date);
    const dateStr = formatDate(expectedDate);
    let daysText = '';
    
    if (task.days_until < 0) {
      daysText = `${Math.abs(task.days_until)} day${Math.abs(task.days_until) !== 1 ? 's' : ''} overdue`;
    } else if (task.days_until === 0) {
      daysText = 'Due today';
    } else if (task.days_until === 1) {
      daysText = 'Due tomorrow';
    } else {
      daysText = `Due in ${task.days_until} days`;
    }
    
    li.innerHTML = `
      <span class="task-channel-icon">${task.channel_icon}</span>
      <span class="task-label">${task.label}</span>
      <span class="task-date">${dateStr}</span>
      <span class="task-days">${daysText}</span>
    `;
    
    return li;
  }

  // Format date
  function formatDate(date) {
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  }

  // Close popup
  function closeTaskPopup() {
    taskPopup.style.display = 'none';
    currentLeadId = null;
  }

  // Event listeners
  taskBells.forEach(bell => {
    bell.addEventListener('click', (e) => {
      e.stopPropagation();
      const leadId = bell.dataset.leadId;
      showTaskPopup(leadId);
    });
  });

  if (taskPopupClose) {
    taskPopupClose.addEventListener('click', closeTaskPopup);
  }

  // Close popup when clicking outside
  taskPopup.addEventListener('click', (e) => {
    if (e.target === taskPopup) {
      closeTaskPopup();
    }
  });

  // Close popup on Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && taskPopup.style.display === 'flex') {
      closeTaskPopup();
    }
  });

  // Load statuses on page load
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadJourneyStatuses);
  } else {
    loadJourneyStatuses();
  }
})();

