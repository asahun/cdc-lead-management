(function() {
  'use strict';

  const STORAGE_KEY = 'lead_app.profile';
  const PROFILES = {
    fisseha: { key: 'fisseha', label: 'Fisseha', email: 'fisseha@loadrouter.com' },
    abby: { key: 'abby', label: 'Abby', email: 'abby@loadrouter.com' },
  };

  let currentKey = 'abby';

  function getConfig(key) {
    return PROFILES[key] || PROFILES.fisseha;
  }

  function getCurrentProfile() {
    const config = getConfig(currentKey);
    return { key: config.key, label: config.label, email: config.email };
  }

  function updateUI(profile) {
    document.querySelectorAll('[data-profile-label]').forEach((el) => {
      el.textContent = profile.label;
    });

    const authorInput = document.getElementById('comment-author-input');
    if (authorInput) {
      authorInput.value = profile.label;
    }
  }

  function persistProfile(key) {
    try {
      window.localStorage.setItem(STORAGE_KEY, key);
    } catch (err) {
      // Ignore storage errors (e.g., private browsing)
    }
  }

  function setProfile(key) {
    if (!PROFILES[key]) {
      key = 'fisseha';
    }

    currentKey = key;
    persistProfile(key);

    const select = document.getElementById('profile-select');
    if (select && select.value !== key) {
      select.value = key;
    }

    const profile = getConfig(key);
    updateUI(profile);

    document.dispatchEvent(
      new CustomEvent('profile:change', {
        detail: getCurrentProfile(),
      })
    );
  }

  window.getCurrentProfile = getCurrentProfile;

  document.addEventListener('DOMContentLoaded', () => {
    let saved = null;
    try {
      saved = window.localStorage.getItem(STORAGE_KEY);
    } catch (err) {
      saved = null;
    }

    setProfile(saved || currentKey);

    const select = document.getElementById('profile-select');
    if (select) {
      select.addEventListener('change', (event) => {
        setProfile(event.target.value);
      });
    }
  });
})();

