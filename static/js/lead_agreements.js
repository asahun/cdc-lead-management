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

  async function fetchDocuments(leadId) {
    const res = await fetch(`/leads/${leadId}/agreements/documents`);
    if (!res.ok) return [];
    const data = await res.json();
    return data.documents || [];
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
    const openClaimLink = $('open-claim-link');
    const createButtons = Array.from(document.querySelectorAll('.create-claim-btn'));
    const statusEl = $('claim-action-status') || $('agreement-status');
    const claimSummaryEl = $('claim-summary');

    if (!createButtons.length && !openClaimLink) return;

    // Derive leadId from dataset on any create button or on body
    const leadId =
      (createButtons[0] && createButtons[0].dataset.leadId) ||
      document.body.dataset.leadId ||
      (openClaimLink && openClaimLink.dataset.leadId);
    if (!leadId) return;

    async function fetchClaim() {
      try {
        const res = await fetch(`/leads/${leadId}/claims/latest`);
        if (res.status === 404) return null;
        if (!res.ok) throw new Error('Failed to load claim');
        return await res.json();
      } catch (err) {
        console.error(err);
        return null;
      }
    }

    function setClaimState(claim) {
      const hasClaim = !!claim;
      if (statusEl && !hasClaim) {
        statusEl.textContent = 'No claim yet. Create a claim to continue.';
        statusEl.className = 'text-muted';
      }
      if (claimSummaryEl) {
        if (hasClaim) {
          const feeDisplay = claim.fee_display || (claim.fee_pct ? `${claim.fee_pct}%` : null) || (claim.fee_flat ? `$${claim.fee_flat}` : null);
          const claimId = claim.claim_id || claim.id;
          const parts = [
            claim.claim_slug || (claimId ? `claim-${claimId}` : 'claim'),
            claim.control_no ? `Control #${claim.control_no}` : null,
            claim.formation_state ? `State ${claim.formation_state}` : null,
            feeDisplay ? `Fee ${feeDisplay}` : null,
            claim.output_dir ? `Output: ${claim.output_dir}` : null,
          ].filter(Boolean);
          claimSummaryEl.textContent = `Claim ready: ${parts.join(' • ')}`;
          claimSummaryEl.className = 'text-success';
        } else {
          claimSummaryEl.textContent = 'No claim yet. Create a claim to continue.';
          claimSummaryEl.className = 'text-muted';
        }
      }
      if (openClaimLink) {
        if (hasClaim) {
          const claimId = claim.claim_id || claim.id;
          openClaimLink.href = `/claims/${claimId}`;
          openClaimLink.style.display = '';
        } else {
          openClaimLink.style.display = 'none';
        }
      }
      createButtons.forEach((b) => (b.disabled = hasClaim));
    }

    async function handleCreateClaim() {
      statusEl.textContent = 'Creating claim...';
      statusEl.className = 'text-muted';
      createButtons.forEach((b) => (b.disabled = true));

      try {
        const res = await fetch(`/leads/${leadId}/claims`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({}),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || 'Claim creation failed');
        }
        const claim = await res.json();
        setClaimState(claim);
        // Navigate to the claim page
        const claimId = claim.claim_id || claim.id;
        if (claimId) {
          window.location.href = `/claims/${claimId}`;
        } else {
          statusEl.textContent = 'Claim created but could not navigate. Please refresh the page.';
          statusEl.className = 'text-warning';
        }
      } catch (e) {
        statusEl.textContent = e.message;
        statusEl.className = 'text-danger';
      } finally {
        createButtons.forEach((b) => (b.disabled = false));
      }
    }

    createButtons.forEach((btn) => btn.addEventListener('click', handleCreateClaim));

    (async () => {
      const claim = await fetchClaim();
      setClaimState(claim);
    })();
  });
})();


