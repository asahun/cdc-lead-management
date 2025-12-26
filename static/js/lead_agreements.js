(function () {
  'use strict';

  function $(id) {
    return document.getElementById(id);
  }

  async function fetchEvents(leadId) {
    const res = await fetch(`/leads/${leadId}/agreements/events`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.events || [];
  }

  function renderEvents(listEl, events) {
    if (!listEl) return;
    listEl.innerHTML = '';
    if (!events.length) {
      const li = document.createElement('li');
      li.textContent = 'No agreement history yet.';
      li.className = 'text-muted';
      listEl.appendChild(li);
      return;
    }
    events.forEach((ev) => {
      const li = document.createElement('li');
      const ts = ev.created_at ? new Date(ev.created_at).toLocaleString() : '';
      const files = ev.payload && ev.payload.files ? ev.payload.files : {};
      const fileText = files.recovery_agreement || files.authorization_letter
        ? ` (files: ${[files.recovery_agreement, files.authorization_letter].filter(Boolean).join(', ')})`
        : '';
      li.textContent = `${ev.state} at ${ts}${fileText}`;
      listEl.appendChild(li);
    });
  }

  document.addEventListener('DOMContentLoaded', () => {
    const section = $('agreement-section');
    if (!section) return;

    const leadId = section.dataset.leadId || document.body.dataset.leadId;
    const controlNoEl = $('agreement-control-no');
    const formationStateEl = $('agreement-formation-state');
    const feePctEl = $('agreement-fee-pct');
    const addendumEl = $('agreement-addendum');
    const statusEl = $('agreement-status');
    const btn = $('generate-agreements-btn');
    const eventsList = $('agreement-events-list');

    async function loadEvents() {
      const events = await fetchEvents(leadId);
      renderEvents(eventsList, events);
    }

    btn?.addEventListener('click', async () => {
      const control_no = (controlNoEl?.value || '').trim();
      const formation_state = (formationStateEl?.value || '').trim();
      const fee_pct = feePctEl?.value || '10';
      const addendum_yes = (addendumEl?.value || 'false') === 'true';

      if (!control_no || !formation_state) {
        statusEl.textContent = 'Control number and formation state are required.';
        statusEl.className = 'text-danger';
        return;
      }

      statusEl.textContent = 'Generating...';
      statusEl.className = 'text-muted';
      btn.disabled = true;
      btn.classList.add('loading');

      try {
        const res = await fetch(`/leads/${leadId}/agreements/generate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ control_no, formation_state, fee_pct, addendum_yes }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || 'Generation failed');
        }
        await loadEvents();
        statusEl.textContent = 'Generated successfully.';
        statusEl.className = 'text-success';
      } catch (e) {
        statusEl.textContent = e.message;
        statusEl.className = 'text-danger';
      } finally {
        btn.disabled = false;
        btn.classList.remove('loading');
      }
    });

    loadEvents();
  });
})();


