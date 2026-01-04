(function () {
  'use strict';

  const api = window.ClaimDetail?.api;
  const render = window.ClaimDetail?.render;
  if (!api || !render) return;

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
    const previewModal = $('preview-modal');
    const previewFrame = $('preview-frame');
    const previewTitle = $('preview-title');
    const previewMeta = $('preview-meta');
    const previewOpenTab = $('preview-open-tab');

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

    const feeTypeEl = $('claim-fee-type');
    const feePctField = $('fee-pct-field');
    const feeFlatField = $('fee-flat-field');
    const feePctEl = $('claim-fee-pct');
    const feeFlatEl = $('claim-fee-flat');

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
    const STATE_LABELS = {
      agreement_file_generated: 'Agreement Generated',
      authorization_file_generated: 'Authorization Generated',
      package_file_uploaded: 'File Uploaded',
      generated_file_deleted: 'Generated File Deleted',
      package_file_deleted: 'Package File Deleted',
      client_claim_data_saved: 'Data Saved',
      claim_created: 'Claim Created',
    };

    let leadPrimaryContactData = null;
    try {
      const contactDataStr = detailCard?.dataset?.leadPrimaryContact;
      if (contactDataStr) {
        leadPrimaryContactData = JSON.parse(contactDataStr);
      }
    } catch (e) {
      console.warn('Failed to parse lead primary contact data', e);
    }

    const state = {
      auditEvents: [],
      docHistory: [],
      currentAuditFilter: 'all',
      pendingDelete: null,
    };

    function openPreview(file) {
      if (!file) return;
      const title = file.name || 'Preview';
      const ts = file.created_at ? new Date(file.created_at).toLocaleString() : '';
      const inlineUrl =
        file.preview_url ||
        (file.download_url
          ? `${file.download_url}${file.download_url.includes('?') ? '&' : '?'}inline=1`
          : '');
      const downloadUrl = inlineUrl || file.download_url || '#';
      if (previewTitle) previewTitle.textContent = title;
      if (previewMeta) previewMeta.textContent = ts;
      if (previewOpenTab) previewOpenTab.href = downloadUrl;
      if (previewFrame && inlineUrl) previewFrame.src = inlineUrl;
      if (previewModal) previewModal.style.display = 'flex';
    }

    function closePreview() {
      if (previewFrame) previewFrame.src = '';
      if (previewModal) previewModal.style.display = 'none';
    }

    function openDeleteModal(type, name) {
      state.pendingDelete = { type, name };
      if (deleteFileNameEl) {
        deleteFileNameEl.textContent = name;
      }
      if (deleteFileModal) {
        deleteFileModal.style.display = 'flex';
      }
    }

    function closeDeleteModal() {
      state.pendingDelete = null;
      if (deleteFileModal) {
        deleteFileModal.style.display = 'none';
      }
    }

    function buildFileToDocType(history) {
      const fileToDocType = {};
      history.forEach((doc) => {
        if (doc.file_path) {
          const fileName = doc.file_path.split('/').pop();
          if (fileName) {
            fileToDocType[fileName] = doc.doc_type;
          }
        }
      });
      return fileToDocType;
    }

    async function refreshEvents() {
      state.auditEvents = await api.fetchEvents(claimId);
      render.updateCurrentStatus($('claim-current-status'), state.auditEvents, STATUS_EVENTS);
      render.renderTimeline(auditList, state.auditEvents, state.currentAuditFilter, {
        statusEvents: STATUS_EVENTS,
        fileEvents: FILE_EVENTS,
        stateLabels: STATE_LABELS,
      });
    }

    async function refreshDocuments() {
      const { generated, packaged, history } = await api.fetchDocuments(claimId);
      const fileToDocType = buildFileToDocType(history);

      render.renderGeneratedFiles(generatedList, generated, {
        onPreview: openPreview,
        onDelete: openDeleteModal,
      });
      render.renderPackageFiles(packageList, packaged, fileToDocType, {
        onPreview: openPreview,
        onDelete: openDeleteModal,
      });
      render.renderRequiredList(requiredList, history);

      render.renderTimeline(auditList, state.auditEvents, state.currentAuditFilter, {
        statusEvents: STATUS_EVENTS,
        fileEvents: FILE_EVENTS,
        stateLabels: STATE_LABELS,
      });
    }

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
      confirmDeleteFileBtn.addEventListener('click', async () => {
        if (!state.pendingDelete) return;
        try {
          await api.deleteFile(claimId, state.pendingDelete.type, state.pendingDelete.name);
          await refreshDocuments();
          await refreshEvents();
          closeDeleteModal();
        } catch (err) {
          alert(err.message);
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
        await api.uploadDocument(claimId, formData);
        uploadStatusEl.textContent = 'Uploaded.';
        uploadStatusEl.className = 'text-success';
        uploadForm.reset();
        await refreshDocuments();
        await refreshEvents();
      } catch (err) {
        uploadStatusEl.textContent = err.message;
        uploadStatusEl.className = 'text-danger';
      }
    });

    if (entitledBusinessSameCheck && entitledBusinessNameEl) {
      entitledBusinessSameCheck.addEventListener('change', () => {
        if (entitledBusinessSameCheck.checked) {
          entitledBusinessNameEl.disabled = true;
          if (detailCard.dataset.ownerName) {
            entitledBusinessNameEl.value = detailCard.dataset.ownerName;
          }
        } else {
          entitledBusinessNameEl.disabled = false;
          if (detailCard.dataset.ownerName && !entitledBusinessNameEl.value.trim()) {
            entitledBusinessNameEl.value = detailCard.dataset.ownerName;
          }
        }
      });
    }

    if (primarySignerSameCheck) {
      const primarySignerInputs = [
        $('primary-signer-first-name'),
        $('primary-signer-last-name'),
        $('primary-signer-title'),
        $('primary-signer-email'),
        $('primary-signer-phone'),
      ];

      primarySignerSameCheck.addEventListener('change', () => {
        primarySignerInputs.forEach((input) => {
          if (!input) return;
          input.disabled = primarySignerSameCheck.checked;
          if (primarySignerSameCheck.checked && leadPrimaryContactData && leadPrimaryContactData.contact_name) {
            const nameParts = (leadPrimaryContactData.contact_name || '').trim().split(/\s+/, 2);
            if (input.id === 'primary-signer-first-name' && nameParts[0]) input.value = nameParts[0];
            if (input.id === 'primary-signer-last-name' && nameParts[1]) input.value = nameParts[1];
            if (input.id === 'primary-signer-title') input.value = leadPrimaryContactData.title || '';
            if (input.id === 'primary-signer-email') input.value = leadPrimaryContactData.email || '';
            if (input.id === 'primary-signer-phone') input.value = leadPrimaryContactData.phone || '';
          } else if (!primarySignerSameCheck.checked && leadPrimaryContactData && leadPrimaryContactData.contact_name) {
            const nameParts = (leadPrimaryContactData.contact_name || '').trim().split(/\s+/, 2);
            if (input.id === 'primary-signer-first-name' && !input.value.trim() && nameParts[0]) input.value = nameParts[0];
            if (input.id === 'primary-signer-last-name' && !input.value.trim() && nameParts[1]) input.value = nameParts[1];
            if (input.id === 'primary-signer-title' && !input.value.trim()) input.value = leadPrimaryContactData.title || '';
            if (input.id === 'primary-signer-email' && !input.value.trim()) input.value = leadPrimaryContactData.email || '';
            if (input.id === 'primary-signer-phone' && !input.value.trim()) input.value = leadPrimaryContactData.phone || '';
          }
        });
      });
    }

    if (checkAddressSameCheck) {
      const addressInputs = [
        $('check-address-street'),
        $('check-address-line2'),
        $('check-address-city'),
        $('check-address-state'),
        $('check-address-zip'),
      ];

      checkAddressSameCheck.addEventListener('change', () => {
        addressInputs.forEach((input) => {
          if (!input) return;
          input.disabled = checkAddressSameCheck.checked;
          if (checkAddressSameCheck.checked && leadPrimaryContactData) {
            if (input.id === 'check-address-street') input.value = leadPrimaryContactData.address_street || '';
            if (input.id === 'check-address-city') input.value = leadPrimaryContactData.address_city || '';
            if (input.id === 'check-address-state') input.value = leadPrimaryContactData.address_state || '';
            if (input.id === 'check-address-zip') input.value = leadPrimaryContactData.address_zipcode || '';
          } else if (!checkAddressSameCheck.checked && leadPrimaryContactData) {
            if (input.id === 'check-address-street' && !input.value.trim()) input.value = leadPrimaryContactData.address_street || '';
            if (input.id === 'check-address-city' && !input.value.trim()) input.value = leadPrimaryContactData.address_city || '';
            if (input.id === 'check-address-state' && !input.value.trim()) input.value = leadPrimaryContactData.address_state || '';
            if (input.id === 'check-address-zip' && !input.value.trim()) input.value = leadPrimaryContactData.address_zipcode || '';
          }
        });
      });
    }

    const secondarySignerEnabled = $('secondary-signer-enabled');
    const secondarySignerFields = $('secondary-signer-fields');
    secondarySignerEnabled?.addEventListener('change', () => {
      if (secondarySignerEnabled.checked) {
        secondarySignerFields.style.display = '';
      } else {
        secondarySignerFields.style.display = 'none';
        const fields = ['first-name', 'last-name', 'title', 'email', 'phone'];
        fields.forEach((field) => {
          const el = $(`secondary-signer-${field}`);
          if (el) el.value = '';
        });
      }
    });

    saveClientClaimInfoBtn?.addEventListener('click', async () => {
      const entitled_business_name = entitledBusinessNameEl?.value?.trim();
      const entitled_business_same_as_owner = entitledBusinessSameCheck?.checked || false;
      const primary_signer_same_as_contact = primarySignerSameCheck?.checked || false;

      const primary_signer = primary_signer_same_as_contact
        ? null
        : {
            first_name: $('primary-signer-first-name')?.value?.trim(),
            last_name: $('primary-signer-last-name')?.value?.trim(),
            title: $('primary-signer-title')?.value?.trim(),
            email: $('primary-signer-email')?.value?.trim(),
            phone: $('primary-signer-phone')?.value?.trim(),
          };

      const secondary_signer_enabled = secondarySignerEnabled?.checked || false;
      const secondary_signer = secondary_signer_enabled
        ? {
            first_name: $('secondary-signer-first-name')?.value?.trim(),
            last_name: $('secondary-signer-last-name')?.value?.trim(),
            title: $('secondary-signer-title')?.value?.trim(),
            email: $('secondary-signer-email')?.value?.trim(),
            phone: $('secondary-signer-phone')?.value?.trim(),
          }
        : null;

      const check_address_same_as_contact = checkAddressSameCheck?.checked || false;
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

      const control_no = controlNoEl?.value?.trim() || null;
      const formation_state = formationStateEl?.value?.trim() || null;
      const fee_type = feeTypeEl?.value || 'percentage';
      const fee_pct = fee_type === 'percentage' ? (feePctEl?.value || '10') : null;
      const fee_flat = fee_type === 'flat' ? (feeFlatEl?.value || null) : null;
      const addendum_yes = addendumEl?.value === 'true';

      try {
        await api.saveClientInfo(claimId, {
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
          secondary_signer_enabled,
          check_address,
          check_address_same_as_contact,
        });
        clientClaimInfoStatus.textContent = 'Saved successfully.';
        clientClaimInfoStatus.className = 'text-success';
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
        await api.generateAgreements(claimId, { control_no, formation_state, fee_pct, fee_flat, addendum_yes });
        await refreshEvents();
        await refreshDocuments();
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
        await api.updateStatus(claimId, newState);
        statusUpdateEl.textContent = 'Updated.';
        statusUpdateEl.className = 'text-success';
        await refreshEvents();
      } catch (err) {
        statusUpdateEl.textContent = err.message;
        statusUpdateEl.className = 'text-danger';
      }
    });

    const auditFilterButtons = Array.from(document.querySelectorAll('.audit-filter-btn'));
    auditFilterButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        auditFilterButtons.forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        state.currentAuditFilter = btn.dataset.filter;
        render.renderTimeline(auditList, state.auditEvents, state.currentAuditFilter, {
          statusEvents: STATUS_EVENTS,
          fileEvents: FILE_EVENTS,
          stateLabels: STATE_LABELS,
        });
      });
    });

    (async () => {
      await refreshDocuments();
      await refreshEvents();
    })();
  });
})();
