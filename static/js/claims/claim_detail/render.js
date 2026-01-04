(function () {
  'use strict';

  function formatDocType(docType) {
    if (!docType) return '';
    return docType
      .split('_')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ');
  }

  function buildDisplayName(filename) {
    if (!filename) return 'file';
    if (!filename.includes('_')) return filename;
    const parts = filename.split('_');
    const hash = parts[0];
    const originalName = parts.slice(1).join('_');
    const extMatch = originalName.match(/\.([^.]+)$/);
    const ext = extMatch ? extMatch[1] : '';
    return ext ? `${hash}.${ext}` : hash;
  }

  function renderTimeline(target, events, filter, options) {
    if (!target) return;
    const statusEvents = options?.statusEvents || [];
    const fileEvents = options?.fileEvents || [];
    const stateLabels = options?.stateLabels || {};

    target.innerHTML = '';
    const sorted = [...events].sort((a, b) => {
      const ta = a.created_at ? new Date(a.created_at).getTime() : 0;
      const tb = b.created_at ? new Date(b.created_at).getTime() : 0;
      return tb - ta;
    });
    const filtered = sorted.filter((ev) => {
      if (filter === 'status') return statusEvents.includes(ev.state);
      if (filter === 'files') return fileEvents.includes(ev.state);
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

      let displayState = ev.state || 'event';
      if (stateLabels[ev.state]) {
        displayState = stateLabels[ev.state];
      }
      badge.textContent = displayState;
      li.appendChild(badge);

      const meta = document.createElement('div');
      meta.className = 'text-muted';
      meta.style.fontSize = '12px';
      const parts = [];

      if (ev.state === 'agreement_file_generated' || ev.state === 'authorization_file_generated') {
        if (payload.file_name) parts.push(payload.file_name);
        if (payload.fee_pct) parts.push(`Fee: ${payload.fee_pct}%`);
        if (payload.fee_flat) parts.push(`Fee: $${payload.fee_flat}`);
      } else if (
        ev.state === 'package_file_uploaded' ||
        ev.state === 'package_file_deleted' ||
        ev.state === 'generated_file_deleted'
      ) {
        if (payload.doc_type) parts.push(payload.doc_type);
        if (payload.name) parts.push(payload.name);
      } else if (ev.state === 'client_claim_data_saved') {
        if (payload.entitled_business_name) parts.push(`Business: ${payload.entitled_business_name}`);
        if (payload.control_no) parts.push(`Control: ${payload.control_no}`);
        if (payload.fee_pct) parts.push(`Fee: ${payload.fee_pct}%`);
        if (payload.fee_flat) parts.push(`Fee: $${payload.fee_flat}`);
      } else {
        if (payload.doc_type) parts.push(payload.doc_type);
        if (payload.name) parts.push(payload.name);
        if (payload.status) parts.push(payload.status);
      }

      meta.textContent = [parts.join(' • '), ts ? ts : null].filter(Boolean).join(' — ');
      li.appendChild(meta);
      target.appendChild(li);
    });
  }

  function updateCurrentStatus(pill, events, statusEvents) {
    if (!pill) return;
    const sorted = [...events]
      .filter((ev) => ev.state && statusEvents.includes(ev.state))
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

  function renderGeneratedFiles(target, files, handlers) {
    if (!target) return;
    target.innerHTML = '';
    if (!files.length) {
      const li = document.createElement('li');
      li.textContent = 'No generated files yet.';
      li.className = 'text-muted';
      target.appendChild(li);
      return;
    }
    files.forEach((file) => {
      const li = document.createElement('li');
      const leftDiv = document.createElement('div');
      leftDiv.style.display = 'flex';
      leftDiv.style.flexDirection = 'column';
      leftDiv.style.gap = '4px';
      const link = document.createElement('a');
      link.href = file.download_url || '#';
      link.textContent = file.name || 'file';
      link.target = '_blank';
      link.style.fontWeight = '500';
      link.style.color = '#3b82f6';
      leftDiv.appendChild(link);
      if (file.created_at) {
        const ts = new Date(file.created_at).toLocaleString();
        const timeSpan = document.createElement('span');
        timeSpan.textContent = ts;
        timeSpan.className = 'text-muted';
        timeSpan.style.fontSize = '12px';
        leftDiv.appendChild(timeSpan);
      }
      li.appendChild(leftDiv);
      const previewBtn = document.createElement('button');
      previewBtn.textContent = 'Preview';
      previewBtn.className = 'btn btn-ghost btn-sm';
      previewBtn.addEventListener('click', () => handlers.onPreview(file));
      const del = document.createElement('button');
      del.textContent = 'Delete';
      del.className = 'btn btn-ghost btn-sm';
      del.addEventListener('click', () => handlers.onDelete('generated', file.name));
      li.appendChild(previewBtn);
      li.appendChild(del);
      target.appendChild(li);
    });
  }

  function renderPackageFiles(target, files, fileToDocType, handlers) {
    if (!target) return;
    target.innerHTML = '';
    if (!files.length) {
      const li = document.createElement('li');
      li.textContent = 'No files uploaded yet.';
      li.className = 'text-muted';
      target.appendChild(li);
      return;
    }
    files.forEach((file) => {
      const displayName = buildDisplayName(file.name || '');
      const docType = fileToDocType[file.name] || '';
      const docTypeLabel = formatDocType(docType);

      const li = document.createElement('li');
      const leftDiv = document.createElement('div');
      leftDiv.style.display = 'flex';
      leftDiv.style.flexDirection = 'column';
      leftDiv.style.gap = '4px';
      const link = document.createElement('a');
      link.href = file.download_url || '#';
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
      if (file.created_at) {
        const ts = new Date(file.created_at).toLocaleString();
        const timeSpan = document.createElement('span');
        timeSpan.textContent = ts;
        timeSpan.className = 'text-muted';
        timeSpan.style.fontSize = '12px';
        leftDiv.appendChild(timeSpan);
      }
      li.appendChild(leftDiv);
      const previewBtn = document.createElement('button');
      previewBtn.textContent = 'Preview';
      previewBtn.className = 'btn btn-ghost btn-sm';
      previewBtn.addEventListener('click', () => handlers.onPreview(file));
      const del = document.createElement('button');
      del.textContent = 'Delete';
      del.className = 'btn btn-ghost btn-sm';
      del.addEventListener('click', () => handlers.onDelete('package', file.name));
      li.appendChild(previewBtn);
      li.appendChild(del);
      target.appendChild(li);
    });
  }

  function renderRequiredList(target, history) {
    if (!target) return;
    const requiredTypes = [
      { key: 'agreement_signed', label: 'Signed Agreement' },
      { key: 'authorization_signed', label: 'Signed Authorization' },
      { key: 'id_verification', label: 'ID Verification' },
      { key: 'fein_document', label: 'FEIN Document' },
    ];
    target.innerHTML = '';
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
      target.appendChild(li);
    });
  }

  window.ClaimDetail = window.ClaimDetail || {};
  window.ClaimDetail.render = {
    renderTimeline,
    updateCurrentStatus,
    renderGeneratedFiles,
    renderPackageFiles,
    renderRequiredList,
  };
})();
