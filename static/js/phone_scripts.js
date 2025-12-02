(function () {
  'use strict';

  document.addEventListener('DOMContentLoaded', () => {
    const section = document.getElementById('phone-scripts');
    if (!section) return;

    const select = document.getElementById('phone-script-select');
    const display = document.getElementById('phone-script-display');
    const copyButton = document.getElementById('copy-phone-script');
    const toggleButton = document.getElementById('phone-script-toggle');

    let scripts = {};
    try {
      const parsed = JSON.parse(section.getAttribute('data-phone-scripts') || '{}');
      if (Array.isArray(parsed)) {
        parsed.forEach((script) => {
          if (script && script.key) {
            scripts[script.key] = script;
          }
        });
      } else if (parsed && typeof parsed === 'object') {
        scripts = parsed;
      }
    } catch (err) {
      scripts = {};
    }

    let scriptContext = {};
    try {
      scriptContext = JSON.parse(section.getAttribute('data-phone-context') || '{}');
    } catch (err) {
      scriptContext = {};
    }
    window.phoneScriptContext = scriptContext;

    let currentScriptKey = select ? select.value : null;
    let isCollapsed = true;

    function applyCollapsedState() {
      if (!section) return;
      if (isCollapsed) {
        section.classList.add('collapsed');
      } else {
        section.classList.remove('collapsed');
      }
      if (toggleButton) {
        toggleButton.textContent = isCollapsed ? 'Show Scripts' : 'Hide Scripts';
        toggleButton.setAttribute('aria-expanded', String(!isCollapsed));
      }
    }

    function buildReplacements(profile) {
      const replacements = {
        OwnerName: scriptContext.OwnerName || '',
        PropertyID: scriptContext.PropertyID || '',
        PropertyAmount: scriptContext.PropertyAmount || '',
        PropertyAmountValue: scriptContext.PropertyAmountValue || '',
        HolderName: scriptContext.HolderName || '',
        ReportYear: scriptContext.ReportYear || '',
        PropertyType: scriptContext.PropertyType || '',
      };

      const prof = profile || (window.getCurrentProfile ? window.getCurrentProfile() : {});
      const firstName = prof.firstName || prof.label || '';
      const lastName = prof.lastName || '';
      const fullName = prof.fullName || (firstName ? `${firstName}${lastName ? ` ${lastName}` : ''}` : prof.label || '');

      replacements.ProfileFirstName = firstName;
      replacements.ProfileLastName = lastName;
      replacements.ProfileFullName = fullName;
      replacements.ProfileEmail = prof.email || '';
      replacements.ProfilePhone = prof.phone || '';

      return replacements;
    }

    function applyPlaceholders(content, profile) {
      if (!content) return '';
      const replacements = buildReplacements(profile);
      return content.replace(/\[([A-Za-z0-9_]+)\]/g, (match, key) => {
        const value = replacements[key];
        if (value === undefined || value === null) {
          return '';
        }
        return value;
      });
    }

    function renderScript(key, profileOverride) {
      if (!display) return;

      const script = scripts[key];
      const profile = profileOverride || (window.getCurrentProfile ? window.getCurrentProfile() : {});

      if (!script) {
        display.innerHTML = '<p class="empty-state">No script available.</p>';
        if (copyButton) {
          copyButton.setAttribute('disabled', 'disabled');
        }
        return;
      }

      currentScriptKey = key;
      const htmlWithValues = applyPlaceholders(script.html || '', profile);
      display.innerHTML = htmlWithValues || '<p class="empty-state">No script available.</p>';

      if (copyButton) {
        copyButton.removeAttribute('disabled');
        copyButton.setAttribute('data-current-key', key);
        copyButton.textContent = 'Copy Script';
      }
    }

    select?.addEventListener('change', (event) => {
      renderScript(event.target.value);
    });

    toggleButton?.addEventListener('click', () => {
      isCollapsed = !isCollapsed;
      applyCollapsedState();
    });

    copyButton?.addEventListener('click', () => {
      if (copyButton.disabled) {
        return;
      }
      const key =
        copyButton.getAttribute('data-current-key') ||
        (select ? select.value : null);
      if (!key || !scripts[key]) {
        return;
      }

      const profile = window.getCurrentProfile ? window.getCurrentProfile() : {};
      const plainText = applyPlaceholders(scripts[key].text || '', profile);
      if (!plainText) {
        alert('Nothing to copy for this script.');
        return;
      }
      if (!navigator.clipboard) {
        alert('Clipboard access is unavailable in this browser.');
        return;
      }

      navigator.clipboard
        .writeText(plainText)
        .then(() => {
          copyButton.textContent = 'Copied!';
          setTimeout(() => {
            copyButton.textContent = 'Copy Script';
          }, 2000);
        })
        .catch(() => {
          alert('Unable to copy script to clipboard.');
        });
    });

    document.addEventListener('profile:change', (event) => {
      if (!currentScriptKey) return;
      renderScript(currentScriptKey, event.detail);
    });

    applyCollapsedState();

    if (select) {
      renderScript(select.value);
    }
  });
})();

