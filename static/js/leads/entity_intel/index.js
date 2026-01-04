(function () {
  'use strict';

  const api = window.EntityIntel?.api;
  const render = window.EntityIntel?.render;
  if (!api || !render) return;

  const button = document.getElementById('run-entity-intel');
  const resultContainer = document.getElementById('entity-intel-result');
  const progressText = document.getElementById('entity-intel-progress');

  if (!button || !resultContainer) {
    return;
  }

  let sosState = {
    records: [],
    searchNameUsed: '',
    flipAllowed: false,
    flipApplied: false,
    selectedIndex: 0,
  };

  async function fetchSosOptions(flip = false) {
    const baseEndpoint = button.dataset.endpoint;
    if (!baseEndpoint) return;
    progressText.hidden = false;
    try {
      const data = await api.fetchSosOptions(baseEndpoint, flip);
      sosState = {
        records: data.sos_records || [],
        searchNameUsed: data.search_name_used || '',
        flipAllowed: Boolean(data.flip_allowed),
        flipApplied: Boolean(data.flip_applied),
        selectedIndex: 0,
      };
      render.renderSosSelector(resultContainer, sosState, {
        onFlip: () => fetchSosOptions(true),
        onRun: () => runAnalysis(false),
        onRunWithoutSos: () => runAnalysis(true),
      });
    } catch (err) {
      console.error('SOS options fetch failed', err);
      resultContainer.classList.add('error-state');
      resultContainer.innerHTML = 'Unable to load SOS options.';
    } finally {
      progressText.hidden = true;
    }
  }

  async function runAnalysis(ignoreSos) {
    const baseEndpoint = button.dataset.endpoint;
    if (!baseEndpoint) return;

    let selectedRecord = null;
    if (!ignoreSos && sosState.records.length > 0) {
      const selectEl = document.getElementById('sos-select');
      const idx = selectEl ? parseInt(selectEl.value, 10) : sosState.selectedIndex || 0;
      sosState.selectedIndex = Number.isNaN(idx) ? 0 : idx;
      selectedRecord = sosState.records[sosState.selectedIndex] || null;
    }

    const body = {
      selected_sos_record: ignoreSos ? null : selectedRecord,
      sos_search_name_used: ignoreSos ? null : sosState.searchNameUsed,
      flip_applied: sosState.flipApplied,
    };

    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    progressText.hidden = false;
    resultContainer.classList.remove('error-state');

    try {
      const data = await api.runAnalysis(baseEndpoint, body);
      render.renderResult(resultContainer, data, data.selected_sos_data);
    } catch (error) {
      console.error('Entity intel fetch failed', error);
      resultContainer.classList.add('error-state');
      resultContainer.innerHTML = 'Unable to load GPT insights. Please try again.';
    } finally {
      progressText.hidden = true;
      button.disabled = false;
      button.removeAttribute('aria-busy');
    }
  }

  function handleClick() {
    sosState = { records: [], searchNameUsed: '', flipAllowed: false, flipApplied: false };
    fetchSosOptions(false);
  }

  button.addEventListener('click', handleClick);
})();
