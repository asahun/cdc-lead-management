(function () {
  'use strict';

  const helpers = window.TaskIndicator?.helpers;
  if (!helpers) return;

  function updateBellIcons(taskBells, journeyStatusCache) {
    taskBells.forEach((bell) => {
      const leadId = bell.dataset.leadId;
      const status = journeyStatusCache[leadId];

      if (!status) {
        bell.classList.remove('bell-overdue', 'bell-due-soon', 'bell-upcoming');
        return;
      }

      bell.classList.remove('bell-overdue', 'bell-due-soon', 'bell-upcoming');

      if (status.priority === 'overdue') {
        bell.classList.add('bell-overdue');
      } else if (status.priority === 'due_soon') {
        bell.classList.add('bell-due-soon');
      } else if (status.priority === 'upcoming') {
        bell.classList.add('bell-upcoming');
      }
    });
  }

  function createTaskListItem(task, category) {
    const li = document.createElement('li');
    li.className = `task-item task-item-${category}`;

    const expectedDate = new Date(task.expected_date);
    const dateStr = helpers.formatDate(expectedDate);
    let daysText = '';

    if (task.days_until < 0) {
      daysText = `${Math.abs(task.days_until)} day${
        Math.abs(task.days_until) !== 1 ? 's' : ''
      } overdue`;
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

  function renderTaskPopup(status, elements) {
    const {
      taskPopupContent,
      taskPopupLoading,
      overdueSection,
      dueSoonSection,
      upcomingSection,
      emptySection,
      overdueList,
      dueSoonList,
      upcomingList,
    } = elements;

    taskPopupLoading.style.display = 'none';
    taskPopupContent.style.display = 'block';

    overdueList.innerHTML = '';
    dueSoonList.innerHTML = '';
    upcomingList.innerHTML = '';

    if (status.overdue.length > 0) {
      overdueSection.style.display = 'block';
      status.overdue.forEach((task) => {
        overdueList.appendChild(createTaskListItem(task, 'overdue'));
      });
    } else {
      overdueSection.style.display = 'none';
    }

    if (status.due_soon.length > 0) {
      dueSoonSection.style.display = 'block';
      status.due_soon.forEach((task) => {
        dueSoonList.appendChild(createTaskListItem(task, 'due-soon'));
      });
    } else {
      dueSoonSection.style.display = 'none';
    }

    if (status.upcoming.length > 0) {
      upcomingSection.style.display = 'block';
      status.upcoming.forEach((task) => {
        upcomingList.appendChild(createTaskListItem(task, 'upcoming'));
      });
    } else {
      upcomingSection.style.display = 'none';
    }

    if (
      status.overdue.length === 0 &&
      status.due_soon.length === 0 &&
      status.upcoming.length === 0
    ) {
      emptySection.style.display = 'block';
    } else {
      emptySection.style.display = 'none';
    }
  }

  window.TaskIndicator = window.TaskIndicator || {};
  window.TaskIndicator.render = {
    updateBellIcons,
    renderTaskPopup,
  };
})();
