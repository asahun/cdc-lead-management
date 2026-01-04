(function() {
  'use strict';

  const STORAGE_KEY = 'lead_app.profile';

  const DEFAULT_PROFILES = {
    abby: {
      key: 'abby',
      label: 'Abby',
      firstName: 'Abby',
      lastName: 'Tezera',
      fullName: 'Abby Tezera',
      email: 'abby@loadrouter.com',
      phone: '(404) 000-0000',
    },
    fisseha: {
      key: 'fisseha',
      label: 'Fisseha',
      firstName: 'Fisseha',
      lastName: 'Gebresilasie',
      fullName: 'Fisseha Gebresilasie',
      email: 'fisseha@loadrouter.com',
      phone: '(404) 000-0000',
    },
  };

  function normalizeProfiles(registry) {
    const normalized = {};
    Object.entries(registry || {}).forEach(([key, value]) => {
      if (!value) return;
      normalized[key] = {
        key,
        label: value.label || value.firstName || key,
        firstName: value.firstName || value.label || key,
        lastName: value.lastName || '',
        fullName: value.fullName || value.label || key,
        email: value.email || '',
        phone: value.phone || '',
      };
    });
    return normalized;
  }

  const registrySource =
    (typeof window.profileRegistry === 'object' && window.profileRegistry)
      ? window.profileRegistry
      : DEFAULT_PROFILES;

  const PROFILES = normalizeProfiles(registrySource);
  const profileKeys = Object.keys(PROFILES);
  const defaultKey = profileKeys.includes('abby')
    ? 'abby'
    : profileKeys[0] || 'fisseha';
  let currentKey = defaultKey;

  function getConfig(key) {
    return PROFILES[key] || PROFILES[defaultKey] || Object.values(PROFILES)[0];
  }

  function getCurrentProfile() {
    const config = getConfig(currentKey);
    return {
      key: config.key,
      label: config.label,
      firstName: config.firstName,
      lastName: config.lastName,
      fullName: config.fullName,
      email: config.email,
      phone: config.phone,
    };
  }

  function updateUI(profile) {
    document.querySelectorAll('[data-profile-label]').forEach((el) => {
      el.textContent = profile.firstName || profile.label || '';
    });

    const authorInput = document.getElementById('comment-author-input');
    if (authorInput) {
      authorInput.value = profile.fullName || profile.label || '';
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
      key = defaultKey;
    }

    currentKey = key;
    persistProfile(key);

    const select = document.getElementById('profile-select');
    if (select && select.value !== key) {
      select.value = key;
    }

    const profile = getCurrentProfile();
    updateUI(profile);

    document.dispatchEvent(
      new CustomEvent('profile:change', {
        detail: profile,
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

