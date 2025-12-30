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
    const addendumEl = $('claim-addendum');
    const statusEl = $('claim-status');
    const generateBtn = $('claim-generate-btn');
    const auditList = $('claim-audit-list');
    const generatedList = $('claim-generated-list');
    const packageList = $('claim-package-list');
    const requiredList = $('claim-required-list');
    
    // Store lead primary contact data for copying (from data attribute)
    let leadPrimaryContactData = null;
    try {
      const contactDataStr = detailCard?.dataset?.leadPrimaryContact;
      if (contactDataStr) {
        leadPrimaryContactData = JSON.parse(contactDataStr);
      }
    } catch (e) {
      console.warn('Failed to parse lead primary contact data', e);
    }
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
      'agreement_file_generated',
      'authorization_file_generated',
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
      'agreement_file_generated',
      'authorization_file_generated',
      'package_file_uploaded',
      'generated_file_deleted',
      'package_file_deleted',
    ];
    const previewModal = $('preview-modal');
    const previewFrame = $('preview-frame');
    const previewTitle = $('preview-title');
    const previewMeta = $('preview-meta');
    const previewOpenTab = $('preview-open-tab');

    // Client/Claim info form elements
    const entitledBusinessSameCheck = $('entitled-business-same-as-owner');
    const entitledBusinessNameEl = $('entitled-business-name');
    const primarySignerSameCheck = $('primary-signer-same-as-contact');
    const primarySignerFields = $('primary-signer-fields');
    const primarySignerDisplay = $('primary-signer-display');
    const checkAddressSameCheck = $('check-address-same-as-contact');
    const checkAddressFields = $('check-address-fields');
    const checkAddressDisplay = $('check-address-display');
    const saveClientClaimInfoBtn = $('save-client-claim-info-btn');
    const clientClaimInfoStatus = $('client-claim-info-status');

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
        let payload = {};
        try {
          payload = typeof ev.payload === 'string' ? JSON.parse(ev.payload) : (ev.payload || {});
        } catch (e) {
          payload = {};
        }
        
        const badge = document.createElement('span');
        badge.className = 'status-pill';
        
        // Format event state for display
        let displayState = ev.state || 'event';
        const stateLabels = {
          'agreement_file_generated': 'Agreement Generated',
          'authorization_file_generated': 'Authorization Generated',
          'package_file_uploaded': 'File Uploaded',
          'generated_file_deleted': 'Generated File Deleted',
          'package_file_deleted': 'Package File Deleted',
          'client_claim_data_saved': 'Data Saved',
          'claim_created': 'Claim Created',
        };
        if (stateLabels[ev.state]) {
          displayState = stateLabels[ev.state];
        }
        badge.textContent = displayState;
        li.appendChild(badge);

        const meta = document.createElement('div');
        meta.className = 'text-muted';
        meta.style.fontSize = '12px';
        const parts = [];
        
        // Format payload information based on event type
        if (ev.state === 'agreement_file_generated' || ev.state === 'authorization_file_generated') {
          if (payload.file_name) parts.push(payload.file_name);
          if (payload.fee_pct) parts.push(`Fee: ${payload.fee_pct}%`);
          if (payload.fee_flat) parts.push(`Fee: $${payload.fee_flat}`);
        } else if (ev.state === 'package_file_uploaded' || ev.state === 'package_file_deleted' || ev.state === 'generated_file_deleted') {
          if (payload.doc_type) parts.push(payload.doc_type);
          if (payload.name) parts.push(payload.name);
        } else if (ev.state === 'client_claim_data_saved') {
          if (payload.entitled_business_name) parts.push(`Business: ${payload.entitled_business_name}`);
          if (payload.control_no) parts.push(`Control: ${payload.control_no}`);
          if (payload.fee_pct) parts.push(`Fee: ${payload.fee_pct}%`);
          if (payload.fee_flat) parts.push(`Fee: $${payload.fee_flat}`);
        } else {
          // Generic payload display
          if (payload.doc_type) parts.push(payload.doc_type);
          if (payload.name) parts.push(payload.name);
          if (payload.status) parts.push(payload.status);
        }
        
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

    function closePreview() {
      if (previewFrame) previewFrame.src = '';
      if (previewModal) previewModal.style.display = 'none';
    }

    function openPreview(file) {
      if (!file) return;
      const title = file.name || 'Preview';
      const ts = file.created_at ? new Date(file.created_at).toLocaleString() : '';
      const inlineUrl = file.preview_url || (file.download_url ? `${file.download_url}${file.download_url.includes('?') ? '&' : '?'}inline=1` : '');
      const downloadUrl = inlineUrl || file.download_url || '#'; // prefer inline for open-tab
      if (previewTitle) previewTitle.textContent = title;
      if (previewMeta) previewMeta.textContent = ts;
      if (previewOpenTab) previewOpenTab.href = downloadUrl;
      if (previewFrame && inlineUrl) previewFrame.src = inlineUrl;
      if (previewModal) previewModal.style.display = 'flex';
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

      if (generatedList) generatedList.innerHTML = '';
      if (packageList) packageList.innerHTML = '';

      if (generatedList) {
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
          const previewBtn = document.createElement('button');
          previewBtn.textContent = 'Preview';
          previewBtn.className = 'btn btn-ghost btn-sm';
          previewBtn.addEventListener('click', () => openPreview(f));
            li.appendChild(previewBtn);
            li.appendChild(del);
            generatedList.appendChild(li);
          });
        }
      }

      if (packageList) {
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
          const previewBtn = document.createElement('button');
          previewBtn.textContent = 'Preview';
          previewBtn.className = 'btn btn-ghost btn-sm';
          previewBtn.addEventListener('click', () => openPreview(f));
            li.appendChild(previewBtn);
            li.appendChild(del);
            packageList.appendChild(li);
          });
        }
      }

      // Always populate required list if element exists
      const requiredListEl = document.getElementById('claim-required-list');
      if (requiredListEl) {
        const requiredTypes = [
          { key: 'agreement_signed', label: 'Signed Agreement' },
          { key: 'authorization_signed', label: 'Signed Authorization' },
          { key: 'id_verification', label: 'ID Verification' },
          { key: 'fein_document', label: 'FEIN Document' },
        ];
        requiredListEl.innerHTML = '';
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
          requiredListEl.appendChild(li);
        });
      }

      // Don't create fake document_record events - use real events from the backend
      // If events already loaded, refresh timeline
      renderTimeline(auditList, auditEvents, currentAuditFilter);
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

    // Preview modal events
    document.querySelectorAll('[data-close-preview]').forEach((btn) => {
      btn.addEventListener('click', closePreview);
    });
    if (previewModal) {
      previewModal.addEventListener('click', (event) => {
        if (event.target === previewModal) {
          closePreview();
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

    // Toggle entitled business name field
    if (entitledBusinessSameCheck && entitledBusinessNameEl) {
      entitledBusinessSameCheck.addEventListener('change', () => {
        if (entitledBusinessSameCheck.checked) {
          entitledBusinessNameEl.disabled = true;
          if (detailCard.dataset.ownerName) {
            entitledBusinessNameEl.value = detailCard.dataset.ownerName;
          }
        } else {
          entitledBusinessNameEl.disabled = false;
          // Copy owner name to field when unchecked (if field is empty)
          if (detailCard.dataset.ownerName && !entitledBusinessNameEl.value.trim()) {
            entitledBusinessNameEl.value = detailCard.dataset.ownerName;
          }
        }
      });
    }

    // Toggle primary signer fields - enable/disable like entitled business name
    if (primarySignerSameCheck) {
      const primarySignerInputs = [
        $('primary-signer-first-name'),
        $('primary-signer-last-name'),
        $('primary-signer-title'),
        $('primary-signer-email'),
        $('primary-signer-phone'),
      ];
      
      primarySignerSameCheck.addEventListener('change', () => {
        primarySignerInputs.forEach(input => {
          if (input) {
            input.disabled = primarySignerSameCheck.checked;
            if (primarySignerSameCheck.checked && leadPrimaryContactData && leadPrimaryContactData.contact_name) {
              // Update values when checked
              const nameParts = (leadPrimaryContactData.contact_name || '').trim().split(/\s+/, 2);
              if (input.id === 'primary-signer-first-name' && nameParts[0]) input.value = nameParts[0];
              if (input.id === 'primary-signer-last-name' && nameParts[1]) input.value = nameParts[1];
              if (input.id === 'primary-signer-title') input.value = leadPrimaryContactData.title || '';
              if (input.id === 'primary-signer-email') input.value = leadPrimaryContactData.email || '';
              if (input.id === 'primary-signer-phone') input.value = leadPrimaryContactData.phone || '';
            } else if (!primarySignerSameCheck.checked && leadPrimaryContactData && leadPrimaryContactData.contact_name) {
              // Copy data when unchecked (if fields are empty)
              const nameParts = (leadPrimaryContactData.contact_name || '').trim().split(/\s+/, 2);
              if (input.id === 'primary-signer-first-name' && !input.value.trim() && nameParts[0]) input.value = nameParts[0];
              if (input.id === 'primary-signer-last-name' && !input.value.trim() && nameParts[1]) input.value = nameParts[1];
              if (input.id === 'primary-signer-title' && !input.value.trim()) input.value = leadPrimaryContactData.title || '';
              if (input.id === 'primary-signer-email' && !input.value.trim()) input.value = leadPrimaryContactData.email || '';
              if (input.id === 'primary-signer-phone' && !input.value.trim()) input.value = leadPrimaryContactData.phone || '';
            }
          }
        });
      });
    }

    // Toggle check address fields - enable/disable like entitled business name
    if (checkAddressSameCheck) {
      const addressInputs = [
        $('check-address-street'),
        $('check-address-line2'),
        $('check-address-city'),
        $('check-address-state'),
        $('check-address-zip'),
      ];
      
      checkAddressSameCheck.addEventListener('change', () => {
        addressInputs.forEach(input => {
          if (input) {
            input.disabled = checkAddressSameCheck.checked;
            if (checkAddressSameCheck.checked && leadPrimaryContactData) {
              // Update values when checked
              if (input.id === 'check-address-street') input.value = leadPrimaryContactData.address_street || '';
              if (input.id === 'check-address-city') input.value = leadPrimaryContactData.address_city || '';
              if (input.id === 'check-address-state') input.value = leadPrimaryContactData.address_state || '';
              if (input.id === 'check-address-zip') input.value = leadPrimaryContactData.address_zipcode || '';
            } else if (!checkAddressSameCheck.checked && leadPrimaryContactData) {
              // Copy data when unchecked (if fields are empty)
              if (input.id === 'check-address-street' && !input.value.trim()) input.value = leadPrimaryContactData.address_street || '';
              if (input.id === 'check-address-city' && !input.value.trim()) input.value = leadPrimaryContactData.address_city || '';
              if (input.id === 'check-address-state' && !input.value.trim()) input.value = leadPrimaryContactData.address_state || '';
              if (input.id === 'check-address-zip' && !input.value.trim()) input.value = leadPrimaryContactData.address_zipcode || '';
            }
          }
        });
      });
    }

    // Toggle secondary signer fields
    const secondarySignerEnabled = $('secondary-signer-enabled');
    const secondarySignerFields = $('secondary-signer-fields');
    secondarySignerEnabled?.addEventListener('change', () => {
      if (secondarySignerEnabled.checked) {
        secondarySignerFields.style.display = '';
      } else {
        secondarySignerFields.style.display = 'none';
        // Clear fields when disabled
        const fields = ['first-name', 'last-name', 'title', 'email', 'phone'];
        fields.forEach(field => {
          const el = $(`secondary-signer-${field}`);
          if (el) el.value = '';
        });
      }
    });

    // Save client/claim information
    saveClientClaimInfoBtn?.addEventListener('click', async () => {
      const entitled_business_name = entitledBusinessNameEl?.value?.trim();
      const entitled_business_same_as_owner = entitledBusinessSameCheck?.checked || false;
      const primary_signer_same_as_contact = primarySignerSameCheck?.checked || false;

      const primary_signer = primary_signer_same_as_contact ? null : {
        first_name: $('primary-signer-first-name')?.value?.trim(),
        last_name: $('primary-signer-last-name')?.value?.trim(),
        title: $('primary-signer-title')?.value?.trim(),
        email: $('primary-signer-email')?.value?.trim(),
        phone: $('primary-signer-phone')?.value?.trim(),
      };

      const secondary_signer_enabled = secondarySignerEnabled?.checked || false;
      const secondary_signer = secondary_signer_enabled ? {
        first_name: $('secondary-signer-first-name')?.value?.trim(),
        last_name: $('secondary-signer-last-name')?.value?.trim(),
        title: $('secondary-signer-title')?.value?.trim(),
        email: $('secondary-signer-email')?.value?.trim(),
        phone: $('secondary-signer-phone')?.value?.trim(),
      } : null;

      const check_address_same_as_contact = checkAddressSameCheck?.checked || false;
      // Always read address values from inputs (even if disabled)
      const check_address = {
        street: $('check-address-street')?.value?.trim() || '',
        line2: $('check-address-line2')?.value?.trim() || '',
        city: $('check-address-city')?.value?.trim() || '',
        state: $('check-address-state')?.value?.trim() || '',
        zip: $('check-address-zip')?.value?.trim() || '',
      };

      if (!entitled_business_name) {
        clientClaimInfoStatus.textContent = 'Entitled business name is required.';
        clientClaimInfoStatus.className = 'text-danger';
        return;
      }

      if (!primary_signer_same_as_contact) {
        if (!primary_signer.first_name || !primary_signer.last_name) {
          clientClaimInfoStatus.textContent = 'Primary signer first and last name are required.';
          clientClaimInfoStatus.className = 'text-danger';
          return;
        }
        if (!primary_signer.title) {
          clientClaimInfoStatus.textContent = 'Primary signer title is required.';
          clientClaimInfoStatus.className = 'text-danger';
          return;
        }
        if (!primary_signer.email) {
          clientClaimInfoStatus.textContent = 'Primary signer email is required.';
          clientClaimInfoStatus.className = 'text-danger';
          return;
        }
        if (!primary_signer.phone) {
          clientClaimInfoStatus.textContent = 'Primary signer phone is required.';
          clientClaimInfoStatus.className = 'text-danger';
          return;
        }
      }

      if (!check_address_same_as_contact) {
        if (!check_address.street || !check_address.city || !check_address.state || !check_address.zip) {
          clientClaimInfoStatus.textContent = 'Check mailing address requires street, city, state, and ZIP.';
          clientClaimInfoStatus.className = 'text-danger';
          return;
        }
      }

      clientClaimInfoStatus.textContent = 'Saving...';
      clientClaimInfoStatus.className = 'text-muted';
      saveClientClaimInfoBtn.disabled = true;

      // Get claim details fields
      const control_no = controlNoEl?.value?.trim() || null;
      const formation_state = formationStateEl?.value?.trim() || null;
      const fee_type = feeTypeEl?.value || 'percentage';
      const fee_pct = fee_type === 'percentage' ? (feePctEl?.value || '10') : null;
      const fee_flat = fee_type === 'flat' ? (feeFlatEl?.value || null) : null;
      const addendum_yes = addendumEl?.value === 'true';

      try {
        const res = await fetch(`/claims/${claimId}/client-info`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            entitled_business_name,
            entitled_business_same_as_owner,
            control_no,
            formation_state,
            fee_type,
            fee_pct,
            fee_flat,
            addendum_yes,
            primary_signer,
            primary_signer_same_as_contact,
            secondary_signer: secondary_signer_enabled ? secondary_signer : null,
            secondary_signer_enabled: secondary_signer_enabled,
            check_address,
            check_address_same_as_contact,
          }),
        });
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.detail || 'Save failed');
        }
        clientClaimInfoStatus.textContent = 'Saved successfully.';
        clientClaimInfoStatus.className = 'text-success';
        // Reload page after a short delay to show updated data
        setTimeout(() => window.location.reload(), 1000);
      } catch (e) {
        clientClaimInfoStatus.textContent = e.message;
        clientClaimInfoStatus.className = 'text-danger';
      } finally {
        saveClientClaimInfoBtn.disabled = false;
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

    // Fee type toggle
    const feeTypeEl = $('claim-fee-type');
    const feePctField = $('fee-pct-field');
    const feeFlatField = $('fee-flat-field');
    const feePctEl = $('claim-fee-pct');
    const feeFlatEl = $('claim-fee-flat');

    feeTypeEl?.addEventListener('change', () => {
      if (feeTypeEl.value === 'percentage') {
        feePctField.style.display = '';
        feeFlatField.style.display = 'none';
      } else {
        feePctField.style.display = 'none';
        feeFlatField.style.display = '';
      }
    });

    generateBtn?.addEventListener('click', async () => {
      const control_no = (controlNoEl?.value || '').trim();
      const formation_state = (formationStateEl?.value || '').trim();
      const fee_type = feeTypeEl?.value || 'percentage';
      const fee_pct = fee_type === 'percentage' ? (feePctEl?.value || '10') : null;
      const fee_flat = fee_type === 'flat' ? (feeFlatEl?.value || null) : null;
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
          body: JSON.stringify({ control_no, formation_state, fee_pct, fee_flat, addendum_yes }),
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

