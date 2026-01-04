(function () {
  'use strict';

  function formatLocalTime(iso) {
    if (!iso) return '';
    const parsed = new Date(iso);
    if (Number.isNaN(parsed.getTime())) {
      return iso;
    }
    return parsed.toLocaleString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  }

  function parseFilenameFromDisposition(headerValue) {
    if (!headerValue) {
      return '';
    }
    const utfMatch = headerValue.match(/filename\*=UTF-8''([^;]+)/i);
    if (utfMatch && utfMatch[1]) {
      return decodeURIComponent(utfMatch[1]);
    }
    const asciiMatch = headerValue.match(/filename="?([^";]+)"?/i);
    return asciiMatch && asciiMatch[1] ? asciiMatch[1] : '';
  }

  function triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename || 'letter.pdf';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  function buildContactSlug(contactName) {
    const normalized = (contactName || '').trim().toLowerCase();
    if (!normalized) return 'letter';
    const slug = normalized.replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '');
    return slug || 'letter';
  }

  window.LetterPrint = window.LetterPrint || {};
  window.LetterPrint.helpers = {
    formatLocalTime,
    parseFilenameFromDisposition,
    triggerDownload,
    buildContactSlug,
  };
})();
