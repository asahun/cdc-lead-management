(function () {
  'use strict';

  function $(id) {
    return document.getElementById(id);
  }

  document.addEventListener('DOMContentLoaded', () => {
    const detailCard = document.querySelector('[data-claim-id]');
    if (!detailCard) return;

    const claimId = detailCard.dataset.claimId;
    const controlNoEl = $('claim-control-no');
    const formationStateEl = $('claim-formation-state');
    const feePctEl = $('claim-fee-pct');
    const addendumEl = $('claim-addendum');
    const statusEl = $('claim-status');
    const generateBtn = $('claim-generate-btn');
    const auditList = $('claim-audit-list');
    const generatedList = $('claim-generated-list');
    const packageList = $('claim-package-list');
    const requiredList = $('claim-required-list');
    const tabs = Array.from(document.querySelectorAll('.tab-btn'));
    const generatedPanel = document.getElementById('generated-panel');
    const packagePanel = document.getElementById('package-panel');
    const uploadForm = $('claim-upload-form');
    const docTypeEl = $('claim-doc-type');
    const notesEl = $('claim-upload-notes');
    const fileEl = $('claim-upload-file');
    const uploadStatusEl = $('claim-upload-status');
    const statusSelect = $('claim-status-select');
    const statusBtn = $('claim-status-btn');
    const statusUpdateEl = $('claim-status-update');
    const deleteFileModal = $('delete-file-modal');
    const deleteFileNameEl = $('delete-file-name');
    const confirmDeleteFileBtn = $('confirm-delete-file');
    const closeDeleteFileButtons = document.querySelectorAll('[data-close-delete-file]');
    const STATUS_EVENTS = [
      'claim_created',
      'agreement_generated',
      'agreement_sent',
      'agreement_signed',
      'claim_preparing',
      'claim_submitted',
      'pending',
      'approved',
      'rejected',
      'more_info',
    ];
    const FILE_EVENTS = [
      'agreement_generated',
      'authorization_generated',
      'document_uploaded',
      'document_deleted',
      'document_record',
    ];

    function renderTimeline(target, events, filter) {
      if (!target) return;
      target.innerHTML = '';
      const sorted = [...events].sort((a, b) => {
        const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
        const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
        return tb - ta;
      });
      const filtered = sorted.filter((ev) => {
        if (filter === 'status') return STATUS_EVENTS.includes(ev.state);
        if (filter === 'files') return FILE_EVENTS.includes(ev.state);
        return true;
      });
      if (!filtered.length) {
        const li = document.createElement('li');
        li.textContent = 'No events yet.';
        li.className = 'text-muted';
        target.appendChild(li);
        return;
      }
      filtered.forEach((ev) => {
        const li = document.createElement('li');
        const ts = ev.created_at ? new Date(ev.created_at).toLocaleString() : '';
        const payload = ev.payload || {};
        const badge = document.createElement('span');
        badge.className = 'status-pill';
        badge.textContent = ev.state || 'event';
        li.appendChild(badge);

        const meta = document.createElement('div');
        meta.className = 'text-muted';
        meta.style.fontSize = '12px';
        const parts = [];
        if (payload.doc_type) parts.push(payload.doc_type);
        if (payload.name) parts.push(payload.name);
        if (payload.status) parts.push(payload.status);
        meta.textContent = [parts.join(' • '), ts ? ts : null].filter(Boolean).join(' — ');
        li.appendChild(meta);
        target.appendChild(li);
      });
    }

    let auditEvents = [];
    let docHistory = [];
    function updateCurrentStatus(events) {
      const pill = $('claim-current-status');
      if (!pill) return;
      const sorted = [...events]
        .filter((ev) => ev.state && STATUS_EVENTS.includes(ev.state))
        .sort((a, b) => {
          const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
          const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
          return tb - ta;
        });
      if (!sorted.length) {
        pill.textContent = '—';
        pill.className = 'text-muted';
        return;
      }
      pill.textContent = sorted[0].state;
      pill.className = 'status-pill';
    }

    async function loadEvents() {
      const res = await fetch(`/claims/${claimId}/events`);
      if (!res.ok) return;
      const data = await res.json();
      auditEvents = data.events || [];
      updateCurrentStatus(auditEvents);
      renderTimeline(auditList, [...auditEvents, ...docHistory], currentAuditFilter);
    }

    async function loadDocuments() {
      if (!generatedList || !packageList) return;

      const [genRes, pkgRes, historyRes] = await Promise.all([
        fetch(`/claims/${claimId}/files?type=generated`),
        fetch(`/claims/${claimId}/files?type=package`),
        fetch(`/claims/${claimId}/documents`),
      ]);

      const generated = genRes.ok ? (await genRes.json()).files || [] : [];
      const packaged = pkgRes.ok ? (await pkgRes.json()).files || [] : [];
      const history = historyRes.ok ? (await historyRes.json()).documents || [] : [];

      // Create a mapping from filename to doc_type
      const fileToDocType = {};
      history.forEach((doc) => {
        if (doc.file_path) {
          const fileName = doc.file_path.split('/').pop();
          if (fileName) {
            fileToDocType[fileName] = doc.doc_type;
          }
        }
      });

      // Helper function to format doc_type
      function formatDocType(docType) {
        if (!docType) return '';
        return docType
          .split('_')
          .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
          .join(' ');
      }

      generatedList.innerHTML = '';
      packageList.innerHTML = '';

      if (!generated.length) {
        const li = document.createElement('li');
        li.textContent = 'No generated files yet.';
        li.className = 'text-muted';
        generatedList.appendChild(li);
      } else {
        generated.forEach((f) => {
          const li = document.createElement('li');
          const leftDiv = document.createElement('div');
          leftDiv.style.display = 'flex';
          leftDiv.style.flexDirection = 'column';
          leftDiv.style.gap = '4px';
          const link = document.createElement('a');
          link.href = f.download_url || '#';
          link.textContent = f.name || 'file';
          link.target = '_blank';
          link.style.fontWeight = '500';
          link.style.color = '#3b82f6';
          leftDiv.appendChild(link);
          if (f.created_at) {
            const ts = new Date(f.created_at).toLocaleString();
            const timeSpan = document.createElement('span');
            timeSpan.textContent = ts;
            timeSpan.className = 'text-muted';
            timeSpan.style.fontSize = '12px';
            leftDiv.appendChild(timeSpan);
          }
          li.appendChild(leftDiv);
          const del = document.createElement('button');
          del.textContent = 'Delete';
          del.className = 'btn btn-ghost btn-sm';
          del.addEventListener('click', () => openDeleteModal('generated', f.name));
          li.appendChild(del);
          generatedList.appendChild(li);
        });
      }

      if (!packaged.length) {
        const li = document.createElement('li');
        li.textContent = 'No files uploaded yet.';
        li.className = 'text-muted';
        packageList.appendChild(li);
      } else {
        packaged.forEach((f) => {
          // Extract hash and extension from filename (format: {hash}_{original_name})
          let displayName = f.name || 'file';
          let docType = fileToDocType[f.name] || '';
          let docTypeLabel = formatDocType(docType);
          
          if (f.name && f.name.includes('_')) {
            const parts = f.name.split('_');
            const hash = parts[0];
            const originalName = parts.slice(1).join('_');
            const extMatch = originalName.match(/\.([^.]+)$/);
            const ext = extMatch ? extMatch[1] : '';
            displayName = ext ? `${hash}.${ext}` : hash;
          }
          
          const li = document.createElement('li');
          const leftDiv = document.createElement('div');
          leftDiv.style.display = 'flex';
          leftDiv.style.flexDirection = 'column';
          leftDiv.style.gap = '4px';
          const link = document.createElement('a');
          link.href = f.download_url || '#';
          link.textContent = displayName;
          link.target = '_blank';
          link.style.fontWeight = '500';
          link.style.color = '#3b82f6';
          leftDiv.appendChild(link);
          if (docTypeLabel) {
            const typeSpan = document.createElement('span');
            typeSpan.textContent = docTypeLabel;
            typeSpan.className = 'text-muted';
            typeSpan.style.fontSize = '12px';
            leftDiv.appendChild(typeSpan);
          }
          if (f.created_at) {
            const ts = new Date(f.created_at).toLocaleString();
            const timeSpan = document.createElement('span');
            timeSpan.textContent = ts;
            timeSpan.className = 'text-muted';
            timeSpan.style.fontSize = '12px';
            leftDiv.appendChild(timeSpan);
          }
          li.appendChild(leftDiv);
          const del = document.createElement('button');
          del.textContent = 'Delete';
          del.className = 'btn btn-ghost btn-sm';
          del.addEventListener('click', () => openDeleteModal('package', f.name));
          li.appendChild(del);
          packageList.appendChild(li);
        });
      }

      if (requiredList) {
        const requiredTypes = [
          { key: 'agreement_signed', label: 'Signed Agreement' },
          { key: 'authorization_signed', label: 'Signed Authorization' },
          { key: 'id_verification', label: 'ID Verification' },
          { key: 'fein_document', label: 'FEIN Document' },
        ];
        requiredList.innerHTML = '';
        requiredTypes.forEach((req) => {
          const hasDoc = history.some((d) => d.doc_type === req.key);
          const li = document.createElement('li');
          const icon = document.createElement('span');
          icon.textContent = hasDoc ? '✓' : '○';
          icon.style.marginRight = '8px';
          icon.style.fontWeight = 'bold';
          icon.style.fontSize = '14px';
          const label = document.createElement('span');
          label.textContent = req.label;
          li.appendChild(icon);
          li.appendChild(label);
          li.className = hasDoc ? 'text-success' : 'text-danger';
          requiredList.appendChild(li);
        });
      }

      docHistory = history.map((d) => ({
        state: 'document_record',
        payload: { doc_type: d.doc_type, name: d.original_name || d.file_path },
        created_at: d.created_at,
      }));

      // If events already loaded, refresh timeline with doc history
      renderTimeline(auditList, [...auditEvents, ...docHistory], currentAuditFilter);
    }

    let pendingDelete = null;

    function openDeleteModal(type, name) {
      pendingDelete = { type, name };
      if (deleteFileNameEl) {
        deleteFileNameEl.textContent = name;
      }
      if (deleteFileModal) {
        deleteFileModal.style.display = 'flex';
      }
    }

    function closeDeleteModal() {
      pendingDelete = null;
      if (deleteFileModal) {
        deleteFileModal.style.display = 'none';
      }
    }

    async function deleteFile(type, name) {
      try {
        const res = await fetch(`/claims/${claimId}/files?type=${encodeURIComponent(type)}&name=${encodeURIComponent(name)}`, {
          method: 'DELETE',
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || 'Delete failed');
        }
        await loadDocuments();
        await loadEvents();
        closeDeleteModal();
      } catch (err) {
        alert(err.message);
      }
    }

    // Modal event listeners
    closeDeleteFileButtons.forEach((btn) => {
      btn.addEventListener('click', closeDeleteModal);
    });

    if (deleteFileModal) {
      deleteFileModal.addEventListener('click', (event) => {
        if (event.target === deleteFileModal) {
          closeDeleteModal();
        }
      });
    }

    if (confirmDeleteFileBtn) {
      confirmDeleteFileBtn.addEventListener('click', () => {
        if (pendingDelete) {
          deleteFile(pendingDelete.type, pendingDelete.name);
        }
      });
    }

    uploadForm?.addEventListener('submit', async (e) => {
      e.preventDefault();
      if (!fileEl?.files?.length) {
        uploadStatusEl.textContent = 'Please choose a file.';
        uploadStatusEl.className = 'text-danger';
        return;
      }
      const formData = new FormData();
      formData.append('doc_type', docTypeEl?.value || 'other');
      formData.append('notes', notesEl?.value || '');
      formData.append('file', fileEl.files[0]);

      uploadStatusEl.textContent = 'Uploading...';
      uploadStatusEl.className = 'text-muted';
      try {
        const res = await fetch(`/claims/${claimId}/documents/upload`, {
          method: 'POST',
          body: formData,
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || 'Upload failed');
        }
        uploadStatusEl.textContent = 'Uploaded.';
        uploadStatusEl.className = 'text-success';
        uploadForm.reset();
        await loadDocuments();
        await loadEvents();
      } catch (err) {
        uploadStatusEl.textContent = err.message;
        uploadStatusEl.className = 'text-danger';
      }
    });

    tabs.forEach((tab) => {
      tab.addEventListener('click', () => {
        tabs.forEach((t) => t.classList.remove('active'));
        tab.classList.add('active');
        const target = tab.dataset.tab;
        if (target === 'generated') {
          generatedPanel.style.display = '';
          packagePanel.style.display = 'none';
        } else {
          generatedPanel.style.display = 'none';
          packagePanel.style.display = '';
        }
      });
    });

    generateBtn?.addEventListener('click', async () => {
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
      generateBtn.disabled = true;
      generateBtn.classList.add('loading');

      try {
        const res = await fetch(`/claims/${claimId}/agreements/generate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ control_no, formation_state, fee_pct, addendum_yes }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || 'Generation failed');
        }
        await loadEvents();
        await loadDocuments();
        statusEl.textContent = 'Generated successfully.';
        statusEl.className = 'text-success';
      } catch (e) {
        statusEl.textContent = e.message;
        statusEl.className = 'text-danger';
      } finally {
        generateBtn.disabled = false;
        generateBtn.classList.remove('loading');
      }
    });

    statusBtn?.addEventListener('click', async () => {
      const newState = statusSelect?.value;
      if (!newState) {
        statusUpdateEl.textContent = 'Choose a status.';
        statusUpdateEl.className = 'text-danger';
        return;
      }
      statusUpdateEl.textContent = 'Updating...';
      statusUpdateEl.className = 'text-muted';
      try {
        const res = await fetch(`/claims/${claimId}/status`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ state: newState }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || 'Failed to update status');
        }
        statusUpdateEl.textContent = 'Updated.';
        statusUpdateEl.className = 'text-success';
        await loadEvents();
      } catch (err) {
        statusUpdateEl.textContent = err.message;
        statusUpdateEl.className = 'text-danger';
      }
    });

    let currentAuditFilter = 'all';
    const auditFilterButtons = Array.from(document.querySelectorAll('.audit-filter-btn'));
    auditFilterButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        auditFilterButtons.forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        currentAuditFilter = btn.dataset.filter;
        renderTimeline(auditList, [...auditEvents, ...docHistory], currentAuditFilter);
      });
    });

    (async () => {
      await loadDocuments();
      await loadEvents();
    })();
  });
})();

