(function () {
  'use strict';

  const api = window.JourneyDisplay?.api;
  const render = window.JourneyDisplay?.render;
  if (!api || !render) return;

  const journeyDisplay = document.getElementById('journey-display');
  if (!journeyDisplay) return;

  const journeySection = journeyDisplay.closest('#journey-tracking');
  const leadStatus = journeySection?.dataset.leadStatus || '';

  const collapsedStatuses = ['response_received', 'claim_created'];
  let isCollapsed = collapsedStatuses.includes(leadStatus);

  const toggleButton = document.getElementById('journey-toggle');
  const goalMessage = document.getElementById('journey-goal-message');

  function applyCollapsedState() {
    if (!journeySection) return;

    if (isCollapsed) {
      journeySection.classList.add('collapsed');
    } else {
      journeySection.classList.remove('collapsed');
    }

    if (goalMessage) {
      if (isCollapsed && collapsedStatuses.includes(leadStatus)) {
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

  applyCollapsedState();

  toggleButton?.addEventListener('click', () => {
    isCollapsed = !isCollapsed;
    applyCollapsedState();
  });

  const leadId = journeyDisplay.dataset.leadId;
  const journeyDataStr = journeyDisplay.dataset.journeyData;

  let journeyData = null;
  try {
    journeyData =
      journeyDataStr && journeyDataStr !== 'null' ? JSON.parse(journeyDataStr) : null;
  } catch (e) {
    console.error('Failed to parse journey data:', e);
  }

  async function renderFromApi() {
    try {
      const data = await api.fetchJourney(leadId);
      if (data.error) {
        journeyDisplay.innerHTML = `<div class="journey-error">${data.error}</div>`;
        applyCollapsedState();
        return;
      }
      render.renderJourney(journeyDisplay, data);
      applyCollapsedState();
    } catch (err) {
      console.error('Failed to fetch journey data:', err);
      journeyDisplay.innerHTML =
        '<div class="journey-error">Failed to load journey data</div>';
      applyCollapsedState();
    }
  }

  if (!journeyData) {
    renderFromApi();
  } else {
    render.renderJourney(journeyDisplay, journeyData);
    applyCollapsedState();
  }
})();
