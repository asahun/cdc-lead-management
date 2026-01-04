(function () {
  'use strict';

  const helpers = window.PropertyManagement?.helpers;
  if (!helpers) return;

  function renderPropertiesList(propertiesList, properties, onSelectionChange) {
    propertiesList.innerHTML = '';

    if (!properties.length) {
      propertiesList.innerHTML =
        '<p style="padding: 20px; text-align: center; color: #6b7280;">No related properties found.</p>';
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
        <th style="text-align: left; padding: 8px;">Address</th>
        <th style="text-align: left; padding: 8px;">Amount</th>
        <th style="text-align: left; padding: 8px;">Year</th>
        <th style="text-align: left; padding: 8px;">Holder Name</th>
      </tr>
    `;
    table.appendChild(thead);

    const tbody = document.createElement('tbody');
    properties.forEach((prop) => {
      const row = document.createElement('tr');
      row.className = 'property-row';
      row.innerHTML = `
        <td style="padding: 10px 8px;">
          <input type="checkbox" class="property-checkbox property-checkbox-small"
            data-property-id="${helpers.escapeHtml(prop.property_id)}"
            data-property-raw-hash="${helpers.escapeHtml(prop.property_raw_hash)}"
            data-property-amount="${prop.property_amount || ''}">
        </td>
        <td style="padding: 10px 8px;">
          <code>${helpers.escapeHtml(prop.property_id)}</code>
        </td>
        <td style="padding: 10px 8px;">
          ${
            prop.owner_name
              ? '<span class="owner-name">' + helpers.escapeHtml(prop.owner_name) + '</span>'
              : '<span class="text-muted">—</span>'
          }
        </td>
        <td style="padding: 10px 8px;">
          ${
            prop.address
              ? helpers.escapeHtml(prop.address)
              : '<span class="text-muted">—</span>'
          }
        </td>
        <td style="padding: 10px 8px;">
          ${
            prop.property_amount
              ? '$' + helpers.formatCurrency(prop.property_amount)
              : '<span class="text-muted">—</span>'
          }
        </td>
        <td style="padding: 10px 8px;">
          ${
            prop.reportyear
              ? helpers.escapeHtml(String(prop.reportyear))
              : '<span class="text-muted">—</span>'
          }
        </td>
        <td style="padding: 10px 8px;">
          ${
            prop.holder_name
              ? helpers.escapeHtml(prop.holder_name)
              : '<span class="text-muted">—</span>'
          }
        </td>
      `;
      tbody.appendChild(row);
    });
    table.appendChild(tbody);
    propertiesList.appendChild(table);

    propertiesList
      .querySelectorAll('input[type="checkbox"].property-checkbox')
      .forEach((cb) => {
        cb.addEventListener('change', onSelectionChange);
      });
  }

  function updateSelectedCount(propertiesList, selectedCountSpan, modalAddBtn) {
    const checkboxes = propertiesList.querySelectorAll(
      'input[type="checkbox"].property-checkbox:checked'
    );
    const count = checkboxes.length;
    selectedCountSpan.textContent = count;
    modalAddBtn.disabled = count === 0;
  }

  function updateSelectAllState(selectAllCheckbox, propertiesList) {
    const checkboxes = propertiesList.querySelectorAll('input[type="checkbox"].property-checkbox');
    const checkedCount = Array.from(checkboxes).filter((cb) => cb.checked).length;
    selectAllCheckbox.checked = checkboxes.length > 0 && checkedCount === checkboxes.length;
    selectAllCheckbox.indeterminate =
      checkedCount > 0 && checkedCount < checkboxes.length;
  }

  window.PropertyManagement = window.PropertyManagement || {};
  window.PropertyManagement.render = {
    renderPropertiesList,
    updateSelectedCount,
    updateSelectAllState,
  };
})();
