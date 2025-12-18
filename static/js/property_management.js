/**
 * Property Management JavaScript
 * Handles adding properties to leads (both existing and new leads)
 */

(function() {
    'use strict';

    // For existing leads: Modal functionality
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

    // For new leads: Related properties selection
    const selectAllRelated = document.getElementById('select-all-related');
    const relatedPropertyCheckboxes = document.querySelectorAll('.related-property-checkbox');
    const additionalPropertiesInput = document.getElementById('additional-properties-input');

    // Initialize for existing leads
    if (addPropertyBtn && addPropertyModal) {
        const leadId = window.location.pathname.match(/\/leads\/(\d+)\//)?.[1];
        if (!leadId) return;

        // Open modal
        addPropertyBtn.addEventListener('click', function() {
            openModal(leadId);
        });

        // Close modal
        modalCancelBtn?.addEventListener('click', closeModal);
        addPropertyModal.addEventListener('click', function(e) {
            if (e.target === addPropertyModal) {
                closeModal();
            }
        });

        // Select all checkbox
        selectAllCheckbox?.addEventListener('change', function() {
            const checkboxes = propertiesList.querySelectorAll('input[type="checkbox"].property-checkbox');
            checkboxes.forEach(cb => {
                cb.checked = selectAllCheckbox.checked;
            });
            updateSelectedCount();
        });

        // Add selected properties
        modalAddBtn?.addEventListener('click', function() {
            addSelectedProperties(leadId);
        });
    }

    // Initialize for new leads
    if (selectAllRelated) {
        selectAllRelated.addEventListener('change', function() {
            relatedPropertyCheckboxes.forEach(cb => {
                cb.checked = selectAllRelated.checked;
            });
            updateAdditionalPropertiesInput();
        });

        relatedPropertyCheckboxes.forEach(cb => {
            cb.addEventListener('change', function() {
                updateSelectAllState();
                updateAdditionalPropertiesInput();
            });
        });
    }

    function openModal(leadId) {
        addPropertyModal.style.display = 'flex';
        modalLoading.style.display = 'block';
        modalContent.style.display = 'none';
        modalErrors.style.display = 'none';
        propertiesList.innerHTML = '';
        selectAllCheckbox.checked = false;
        updateSelectedCount();

        // Fetch related properties
        fetch(`/leads/${leadId}/properties/related`)
            .then(response => response.json())
            .then(data => {
                modalLoading.style.display = 'none';
                modalContent.style.display = 'block';

                if (data.properties && data.properties.length > 0) {
                    // Get owner name from page
                    const ownerNameEl = document.querySelector('.properties-section h2 .owner-name');
                    if (ownerNameEl) {
                        modalOwnerName.textContent = ownerNameEl.textContent;
                        modalOwnerName.className = 'owner-name';
                    }

                    renderPropertiesList(data.properties);
                } else {
                    propertiesList.innerHTML = '<p style="padding: 20px; text-align: center; color: #6b7280;">No related properties found.</p>';
                }
            })
            .catch(error => {
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

    function renderPropertiesList(properties) {
        propertiesList.innerHTML = '';
        
        if (properties.length === 0) {
            propertiesList.innerHTML = '<p style="padding: 20px; text-align: center; color: #6b7280;">No related properties found.</p>';
            return;
        }

        const table = document.createElement('table');
        table.className = 'related-properties-table';
        table.style.width = '100%';

        const thead = document.createElement('thead');
        thead.innerHTML = `
            <tr style="border-bottom: 1px solid #e5e7eb;">
                <th style="text-align: left; padding: 8px; width: 40px;"></th>
                <th style="text-align: left; padding: 8px;">Property ID</th>
                <th style="text-align: left; padding: 8px;">Owner Name</th>
                <th style="text-align: left; padding: 8px;">Amount</th>
                <th style="text-align: left; padding: 8px;">Year</th>
                <th style="text-align: left; padding: 8px;">Holder Name</th>
            </tr>
        `;
        table.appendChild(thead);

        const tbody = document.createElement('tbody');
        properties.forEach(prop => {
            const row = document.createElement('tr');
            row.className = 'property-row';
            row.innerHTML = `
                <td style="padding: 10px 8px;">
                    <input type="checkbox" class="property-checkbox property-checkbox-small" 
                           data-property-id="${escapeHtml(prop.property_id)}"
                           data-property-raw-hash="${escapeHtml(prop.property_raw_hash)}"
                           data-property-amount="${prop.property_amount || ''}">
                </td>
                <td style="padding: 10px 8px;">
                    <code>${escapeHtml(prop.property_id)}</code>
                </td>
                <td style="padding: 10px 8px;">
                    ${prop.owner_name ? '<span class="owner-name">' + escapeHtml(prop.owner_name) + '</span>' : '<span class="text-muted">—</span>'}
                </td>
                <td style="padding: 10px 8px;">
                    ${prop.property_amount ? '$' + formatCurrency(prop.property_amount) : '<span class="text-muted">—</span>'}
                </td>
                <td style="padding: 10px 8px;">
                    ${prop.reportyear ? escapeHtml(String(prop.reportyear)) : '<span class="text-muted">—</span>'}
                </td>
                <td style="padding: 10px 8px;">
                    ${prop.holder_name ? escapeHtml(prop.holder_name) : '<span class="text-muted">—</span>'}
                </td>
            `;
            tbody.appendChild(row);
        });
        table.appendChild(tbody);
        propertiesList.appendChild(table);

        // Add event listeners to checkboxes
        const checkboxes = propertiesList.querySelectorAll('input[type="checkbox"].property-checkbox');
        checkboxes.forEach(cb => {
            cb.addEventListener('change', function() {
                updateSelectedCount();
                updateSelectAllState();
            });
        });
    }

    function updateSelectedCount() {
        const checkboxes = propertiesList.querySelectorAll('input[type="checkbox"].property-checkbox:checked');
        const count = checkboxes.length;
        selectedCountSpan.textContent = count;
        modalAddBtn.disabled = count === 0;
    }

    function updateSelectAllState() {
        const checkboxes = propertiesList.querySelectorAll('input[type="checkbox"].property-checkbox');
        const checkedCount = Array.from(checkboxes).filter(cb => cb.checked).length;
        selectAllCheckbox.checked = checkboxes.length > 0 && checkedCount === checkboxes.length;
        selectAllCheckbox.indeterminate = checkedCount > 0 && checkedCount < checkboxes.length;
    }

    function addSelectedProperties(leadId) {
        const checkboxes = propertiesList.querySelectorAll('input[type="checkbox"].property-checkbox:checked');
        const selectedProperties = Array.from(checkboxes).map(cb => ({
            property_id: cb.dataset.propertyId,
            property_raw_hash: cb.dataset.propertyRawHash,
            property_amount: cb.dataset.propertyAmount ? parseFloat(cb.dataset.propertyAmount) : null
        }));

        if (selectedProperties.length === 0) {
            return;
        }

        // Disable button during submission
        modalAddBtn.disabled = true;
        modalAddBtn.textContent = 'Adding...';

        // Create form and submit
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

    // For new leads: Update additional properties input
    function updateAdditionalPropertiesInput() {
        if (!additionalPropertiesInput) return;

        const selected = Array.from(relatedPropertyCheckboxes)
            .filter(cb => cb.checked)
            .map(cb => ({
                property_id: cb.dataset.propertyId,
                property_raw_hash: cb.dataset.propertyRawHash,
                property_amount: cb.dataset.propertyAmount ? parseFloat(cb.dataset.propertyAmount) : null
            }));

        additionalPropertiesInput.value = JSON.stringify(selected);
    }

    function updateSelectAllState() {
        if (!selectAllRelated) return;
        const checkedCount = Array.from(relatedPropertyCheckboxes).filter(cb => cb.checked).length;
        selectAllRelated.checked = relatedPropertyCheckboxes.length > 0 && checkedCount === relatedPropertyCheckboxes.length;
        selectAllRelated.indeterminate = checkedCount > 0 && checkedCount < relatedPropertyCheckboxes.length;
    }

  // Initialize select all state for new leads
  if (selectAllRelated && relatedPropertyCheckboxes.length > 0) {
    updateSelectAllState();
  }

  // Remove Property Confirmation Modal
  const removePropertyModal = document.getElementById('remove-property-modal');
  const removePropertyForm = document.getElementById('remove-property-form');
  const removePropertyDetails = document.getElementById('remove-property-details');
  const removePropertyButtons = document.querySelectorAll('.remove-property-btn');
  const closeRemovePropertyButtons = document.querySelectorAll('[data-close-remove-property]');

  if (removePropertyModal && removePropertyButtons.length > 0) {
    // Open modal when remove button is clicked
    removePropertyButtons.forEach(btn => {
      btn.addEventListener('click', function() {
        const propertyId = btn.dataset.propertyId;
        const formAction = btn.dataset.propertyFormAction;
        
        // Set form action
        if (removePropertyForm) {
          removePropertyForm.action = formAction;
        }
        
        // Set property details
        if (removePropertyDetails) {
          removePropertyDetails.textContent = `Property ID: ${propertyId}`;
        }
        
        // Show modal
        if (removePropertyModal) {
          removePropertyModal.style.display = 'flex';
        }
      });
    });

    // Close modal
    closeRemovePropertyButtons.forEach(btn => {
      btn.addEventListener('click', function() {
        if (removePropertyModal) {
          removePropertyModal.style.display = 'none';
        }
      });
    });

    // Close modal on backdrop click
    removePropertyModal.addEventListener('click', function(e) {
      if (e.target === removePropertyModal) {
        removePropertyModal.style.display = 'none';
      }
    });

    // Close modal on Escape key
    document.addEventListener('keydown', function(e) {
      if (e.key === 'Escape' && removePropertyModal.style.display === 'flex') {
        removePropertyModal.style.display = 'none';
      }
    });
  }

  // Utility functions
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  function formatCurrency(amount) {
    return new Intl.NumberFormat('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2
    }).format(amount);
  }
})();

