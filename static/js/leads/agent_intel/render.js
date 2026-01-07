(function () {
  'use strict';

  function escapeHtml(value) {
    return String(value || '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatTimestamp(value) {
    if (!value) return '—';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
  }

  function renderEvidence(items) {
    if (!items || items.length === 0) {
      return '<p class="text-muted-info">No evidence collected yet.</p>';
    }

    const list = items
      .map((item) => {
        const title = escapeHtml(item.title || 'Untitled');
        const url = escapeHtml(item.url || '#');
        const snippet = escapeHtml(item.snippet || '');
        const source = escapeHtml(item.source || 'unknown');
        const confidence = typeof item.confidence === 'number' ? item.confidence.toFixed(2) : '0.00';
        return `
          <li class="intel-item">
            <div class="intel-item-header">
              <span class="intel-tag">${source}</span>
              <a href="${url}" target="_blank" rel="noopener">${title}</a>
              <span class="intel-muted">conf ${confidence}</span>
            </div>
            <p>${snippet}</p>
          </li>
        `;
      })
      .join('');

    return `<ul class="intel-list">${list}</ul>`;
  }

  function renderNextActions(items) {
    if (!items || items.length === 0) {
      return '<p class="text-muted-info">No next actions yet.</p>';
    }

    return `<ul class="intel-list">${items.map((item) => `<li>${escapeHtml(item)}</li>`).join('')}</ul>`;
  }

  function renderAudit(audit) {
    if (!audit || !Array.isArray(audit.steps) || audit.steps.length === 0) {
      return '<p class="text-muted-info">No audit steps recorded.</p>';
    }

    const steps = audit.steps
      .map((step) => {
        const name = escapeHtml(step.name || 'step');
        const started = formatTimestamp(step.started_at);
        const ended = formatTimestamp(step.ended_at);
        const notes = escapeHtml(step.notes || '');
        return `<li><strong>${name}</strong> (${started} → ${ended}) ${notes ? `— ${notes}` : ''}</li>`;
      })
      .join('');

    return `<ul class="intel-list">${steps}</ul>`;
  }

  function renderResult(container, payload) {
    if (!payload || !payload.result) {
      container.classList.add('empty-state');
      container.innerHTML = 'No agent research yet. Click "Run Agent Research" to generate a snapshot.';
      return;
    }

    const result = payload.result;
    container.classList.remove('empty-state', 'error-state');

    const entityRender = window.EntityIntel?.render?.renderResult;
    const analysis = result.analysis || (result.query_context ? result : null);
    if (analysis && entityRender) {
      entityRender(
        container,
        { analysis, selected_sos_data: analysis.context_inputs?.ga_sos_selected_record || null },
        analysis.context_inputs?.ga_sos_selected_record || null
      );
      return;
    }

    const scenario = escapeHtml(result.scenario || 'unknown');
    const profile = result.entity_profile || {};
    const entityName = escapeHtml(profile.business_name || '—');
    const entityState = escapeHtml(profile.state || '—');
    const entityStatus = escapeHtml(profile.status || '—');

    container.innerHTML = `
      <div class="intel-section">
        <p><strong>Scenario:</strong> ${scenario}</p>
        <p><strong>Entity:</strong> ${entityName} (${entityState})</p>
        <p><strong>Status (from sources):</strong> ${entityStatus}</p>
        <p><strong>Last Run:</strong> ${formatTimestamp(payload.created_at)}</p>
      </div>
      <div class="intel-section">
        <h3>Evidence</h3>
        ${renderEvidence(result.evidence || [])}
      </div>
      <div class="intel-section">
        <h3>Next Actions</h3>
        ${renderNextActions(result.next_actions || [])}
      </div>
      <div class="intel-section">
        <h3>Audit</h3>
        ${renderAudit(result.audit)}
      </div>
    `;
  }

  window.AgentIntel = window.AgentIntel || {};
  window.AgentIntel.render = { renderResult };
})();
