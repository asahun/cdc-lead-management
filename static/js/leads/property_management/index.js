(function () {
  'use strict';

  const api = window.PropertyManagement?.api;
  const render = window.PropertyManagement?.render;
  if (!api || !render) return;

  const addPropertyBtn = document.getElementById('add-property-btn');
  const addPropertyModal = document.getElementById('add-property-modal');
  const modalCancelBtn = document.getElementById('modal-cancel-btn');
  const modalAddBtn = document.getElementById('modal-add-btn');
  const selectAllCheckbox = document.getElementById('select-all-properties');
  const propertiesList = document.getElementById('properties-list');
  const modalLoading = document.getElementById('modal-loading');
  const modalContent = document.getElementById('modal-content');
  const modalOwnerName = document.getElementById('modal-owner-name');
  const selectedCountSpan = document.getElementById('selected-count');
  const modalErrors = document.getElementById('modal-errors');

  const selectAllRelated = document.getElementById('select-all-related');
  const relatedPropertyCheckboxes = document.querySelectorAll('.related-property-checkbox');
  const additionalPropertiesInput = document.getElementById('additional-properties-input');

  const removePropertyModal = document.getElementById('remove-property-modal');
  const removePropertyForm = document.getElementById('remove-property-form');
  const removePropertyDetails = document.getElementById('remove-property-details');
  const removePropertyButtons = document.querySelectorAll('.remove-property-btn');
  const closeRemovePropertyButtons = document.querySelectorAll('[data-close-remove-property]');

  function getLeadIdFromPath() {
    return window.location.pathname.match(/\/leads\/(\d+)\//)?.[1];
  }

  function openModal(leadId) {
    addPropertyModal.style.display = 'flex';
    modalLoading.style.display = 'block';
    modalContent.style.display = 'none';
    modalErrors.style.display = 'none';
    propertiesList.innerHTML = '';
    selectAllCheckbox.checked = false;

    const flipNamesCheckbox = document.getElementById('flip-names-checkbox');
    render.updateSelectedCount(propertiesList, selectedCountSpan, modalAddBtn);

    const flip = flipNamesCheckbox ? flipNamesCheckbox.checked : false;

    api.fetchRelatedProperties(leadId, flip)
      .then((data) => {
        modalLoading.style.display = 'none';
        modalContent.style.display = 'block';

        if (data.properties && data.properties.length > 0) {
          const ownerNameEl = document.querySelector('.properties-section h2 .owner-name');
          if (ownerNameEl) {
            modalOwnerName.textContent = ownerNameEl.textContent;
            modalOwnerName.className = 'owner-name';
          }

          render.renderPropertiesList(propertiesList, data.properties, () => {
            render.updateSelectedCount(propertiesList, selectedCountSpan, modalAddBtn);
            render.updateSelectAllState(selectAllCheckbox, propertiesList);
          });
        } else {
          propertiesList.innerHTML =
            '<p style="padding: 20px; text-align: center; color: #6b7280;">No related properties found.</p>';
        }
      })
      .catch((error) => {
        console.error('Error fetching related properties:', error);
        modalLoading.style.display = 'none';
        modalContent.style.display = 'block';
        modalErrors.style.display = 'block';
        modalErrors.textContent = 'Error loading properties. Please try again.';
      });
  }

  function closeModal() {
    addPropertyModal.style.display = 'none';
  }

  function addSelectedProperties(leadId) {
    const checkboxes = propertiesList.querySelectorAll(
      'input[type="checkbox"].property-checkbox:checked'
    );
    const selectedProperties = Array.from(checkboxes).map((cb) => ({
      property_id: cb.dataset.propertyId,
      property_raw_hash: cb.dataset.propertyRawHash,
      property_amount: cb.dataset.propertyAmount
        ? parseFloat(cb.dataset.propertyAmount)
        : null,
    }));

    if (!selectedProperties.length) {
      return;
    }

    modalAddBtn.disabled = true;
    modalAddBtn.textContent = 'Adding...';

    const form = document.createElement('form');
    form.method = 'POST';
    form.action = `/leads/${leadId}/properties/add-bulk`;

    const input = document.createElement('input');
    input.type = 'hidden';
    input.name = 'property_ids';
    input.value = JSON.stringify(selectedProperties);
    form.appendChild(input);

    document.body.appendChild(form);
    form.submit();
  }

  function updateAdditionalPropertiesInput() {
    if (!additionalPropertiesInput) return;

    const selected = Array.from(relatedPropertyCheckboxes)
      .filter((cb) => cb.checked)
      .map((cb) => ({
        property_id: cb.dataset.propertyId,
        property_raw_hash: cb.dataset.propertyRawHash,
        property_amount: cb.dataset.propertyAmount ? parseFloat(cb.dataset.propertyAmount) : null,
      }));

    additionalPropertiesInput.value = JSON.stringify(selected);
  }

  function updateSelectAllRelatedState() {
    if (!selectAllRelated) return;
    const checkedCount = Array.from(relatedPropertyCheckboxes).filter((cb) => cb.checked).length;
    selectAllRelated.checked =
      relatedPropertyCheckboxes.length > 0 &&
      checkedCount === relatedPropertyCheckboxes.length;
    selectAllRelated.indeterminate =
      checkedCount > 0 && checkedCount < relatedPropertyCheckboxes.length;
  }

  function initExistingLeadModal() {
    if (!addPropertyBtn || !addPropertyModal) return;
    const leadId = getLeadIdFromPath();
    if (!leadId) return;

    addPropertyBtn.addEventListener('click', () => openModal(leadId));
    modalCancelBtn?.addEventListener('click', closeModal);
    addPropertyModal.addEventListener('click', (e) => {
      if (e.target === addPropertyModal) {
        closeModal();
      }
    });

    selectAllCheckbox?.addEventListener('change', () => {
      const checkboxes = propertiesList.querySelectorAll(
        'input[type="checkbox"].property-checkbox'
      );
      checkboxes.forEach((cb) => {
        cb.checked = selectAllCheckbox.checked;
      });
      render.updateSelectedCount(propertiesList, selectedCountSpan, modalAddBtn);
    });

    const flipNamesCheckbox = document.getElementById('flip-names-checkbox');
    flipNamesCheckbox?.addEventListener('change', () => {
      openModal(leadId);
    });

    modalAddBtn?.addEventListener('click', () => {
      addSelectedProperties(leadId);
    });
  }

  function initNewLeadSelection() {
    if (!selectAllRelated) return;
    selectAllRelated.addEventListener('change', () => {
      relatedPropertyCheckboxes.forEach((cb) => {
        cb.checked = selectAllRelated.checked;
      });
      updateAdditionalPropertiesInput();
    });

    relatedPropertyCheckboxes.forEach((cb) => {
      cb.addEventListener('change', () => {
        updateSelectAllRelatedState();
        updateAdditionalPropertiesInput();
      });
    });

    if (relatedPropertyCheckboxes.length > 0) {
      updateSelectAllRelatedState();
    }
  }

  function initRemovePropertyModal() {
    if (!removePropertyModal || removePropertyButtons.length === 0) return;

    removePropertyButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        const propertyId = btn.dataset.propertyId;
        const formAction = btn.dataset.propertyFormAction;

        if (removePropertyForm) {
          removePropertyForm.action = formAction;
        }

        if (removePropertyDetails) {
          removePropertyDetails.textContent = `Property ID: ${propertyId}`;
        }

        removePropertyModal.style.display = 'flex';
      });
    });

    closeRemovePropertyButtons.forEach((btn) => {
      btn.addEventListener('click', () => {
        removePropertyModal.style.display = 'none';
      });
    });

    removePropertyModal.addEventListener('click', (e) => {
      if (e.target === removePropertyModal) {
        removePropertyModal.style.display = 'none';
      }
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && removePropertyModal.style.display === 'flex') {
        removePropertyModal.style.display = 'none';
      }
    });
  }

  initExistingLeadModal();
  initNewLeadSelection();
  initRemovePropertyModal();
})();
