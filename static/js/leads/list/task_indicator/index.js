(function () {
  'use strict';

  const api = window.TaskIndicator?.api;
  const helpers = window.TaskIndicator?.helpers;
  const render = window.TaskIndicator?.render;
  if (!api || !helpers || !render) return;

  const taskBells = document.querySelectorAll('.task-bell');
  const taskPopup = document.getElementById('task-popup');
  const taskPopupContent = document.getElementById('task-popup-content');
  const taskPopupLoading = document.getElementById('task-popup-loading');
  const taskPopupClose = document.querySelector('.task-popup-close');

  const overdueSection = document.getElementById('task-overdue-section');
  const dueSoonSection = document.getElementById('task-due-soon-section');
  const upcomingSection = document.getElementById('task-upcoming-section');
  const emptySection = document.getElementById('task-empty');
  const overdueList = document.getElementById('task-overdue-list');
  const dueSoonList = document.getElementById('task-due-soon-list');
  const upcomingList = document.getElementById('task-upcoming-list');

  let currentLeadId = null;
  let journeyStatusCache = {};

  const popupElements = {
    taskPopupContent,
    taskPopupLoading,
    overdueSection,
    dueSoonSection,
    upcomingSection,
    emptySection,
    overdueList,
    dueSoonList,
    upcomingList,
  };

  async function loadJourneyStatuses() {
    const leadIds = Array.from(taskBells).map((bell) => bell.dataset.leadId);
    if (!leadIds.length) return;

    try {
      journeyStatusCache = await api.fetchJourneyStatuses(leadIds);
      render.updateBellIcons(taskBells, journeyStatusCache);
    } catch (err) {
      console.error('Failed to load journey statuses:', err);
    }
  }

  async function showTaskPopup(leadId) {
    currentLeadId = leadId;
    taskPopup.style.display = 'flex';
    taskPopupContent.style.display = 'none';
    taskPopupLoading.style.display = 'block';

    const cachedStatus = journeyStatusCache[leadId];
    if (cachedStatus) {
      render.renderTaskPopup(cachedStatus, popupElements);
      return;
    }

    try {
      const journeyData = await api.fetchJourney(leadId);
      const summary = helpers.convertJourneyToSummary(journeyData);
      journeyStatusCache[leadId] = summary;
      render.renderTaskPopup(summary, popupElements);
    } catch (err) {
      console.error('Failed to load task details:', err);
      taskPopupLoading.textContent = 'Failed to load tasks';
    }
  }

  function closeTaskPopup() {
    taskPopup.style.display = 'none';
    currentLeadId = null;
  }

  taskBells.forEach((bell) => {
    bell.addEventListener('click', (e) => {
      e.stopPropagation();
      showTaskPopup(bell.dataset.leadId);
    });
  });

  if (taskPopupClose) {
    taskPopupClose.addEventListener('click', closeTaskPopup);
  }

  taskPopup.addEventListener('click', (e) => {
    if (e.target === taskPopup) {
      closeTaskPopup();
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && taskPopup.style.display === 'flex') {
      closeTaskPopup();
    }
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', loadJourneyStatuses);
  } else {
    loadJourneyStatuses();
  }
})();
