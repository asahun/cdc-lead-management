(function () {
  'use strict';

  const api = window.AgentIntel?.api;
  const render = window.AgentIntel?.render;
  if (!api || !render) return;

  const button = document.getElementById('run-agent-intel');
  const resultContainer = document.getElementById('agent-intel-result');
  const progressText = document.getElementById('agent-intel-progress');

  if (!button || !resultContainer) return;

  const baseEndpoint = button.dataset.endpoint;

  async function loadLatest() {
    if (!baseEndpoint) return;
    try {
      const data = await api.fetchLatest(baseEndpoint);
      render.renderResult(resultContainer, data);
    } catch (error) {
      console.error('Agent intel load failed', error);
    }
  }

  async function runAgent() {
    if (!baseEndpoint) return;
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    progressText.hidden = false;
    resultContainer.classList.remove('error-state');

    try {
      const data = await api.run(baseEndpoint);
      render.renderResult(resultContainer, data);
    } catch (error) {
      console.error('Agent intel run failed', error);
      resultContainer.classList.add('error-state');
      resultContainer.innerHTML = 'Unable to run agent research. Please try again.';
    } finally {
      progressText.hidden = true;
      button.disabled = false;
      button.removeAttribute('aria-busy');
    }
  }

  button.addEventListener('click', runAgent);
  loadLatest();
})();
