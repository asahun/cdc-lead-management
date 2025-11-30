(function () {
  const dialog = document.getElementById("property-detail-dialog");
  if (!dialog) {
    return;
  }

  const modalBody = dialog.querySelector(".modal-body");

  function buildDetailUrl(path, options = {}) {
    const url = new URL(path, window.location.origin);
    if (options.context) {
      url.searchParams.set("context", options.context);
    }
    return url.toString();
  }

  async function loadDetail(propertyId, options = {}) {
    const url = buildDetailUrl(`/properties/${encodeURIComponent(propertyId)}`, options);
    const response = await fetch(url);
    if (!response.ok) {
      modalBody.innerHTML = `<div class="modal-error">Unable to load property ${propertyId}</div>`;
      return;
    }

    const html = await response.text();
    modalBody.innerHTML = html;

    wireDetailControls();
  }

  async function loadDetailByOrder(orderId, options = {}) {
    const url = buildDetailUrl(`/properties/by_order/${encodeURIComponent(orderId)}`, options);
    const response = await fetch(url);
    if (!response.ok) {
      modalBody.innerHTML = `<div class="modal-error">Unable to load property order #${orderId}</div>`;
      return;
    }

    const html = await response.text();
    modalBody.innerHTML = html;

    wireDetailControls();
  }

  async function loadDetailByHash(rawHash, options = {}) {
    const url = buildDetailUrl(`/properties/by_hash/${encodeURIComponent(rawHash)}`, options);
    const response = await fetch(url);
    if (!response.ok) {
      modalBody.innerHTML = `<div class="modal-error">Unable to load property details</div>`;
      return;
    }

    const html = await response.text();
    modalBody.innerHTML = html;

    wireDetailControls();
  }

  function wireDetailControls() {
    const card = modalBody.querySelector(".property-detail-card");
    if (!card) {
      return;
    }

    const currentId = card.dataset.propertyId;
    const currentOrderId = parseInt(card.dataset.orderId || "", 10);
    const currentRawHash = card.dataset.rawHash || "";
    dialog.dataset.currentId = currentId;
    dialog.dataset.currentOrderId = Number.isNaN(currentOrderId) ? "" : currentOrderId;
    dialog.dataset.currentHash = currentRawHash;

    const closeBtn = card.querySelector(".detail-close");
    if (closeBtn) {
      closeBtn.addEventListener("click", closeDialog);
    }

    const prevBtn = card.querySelector(".detail-prev");
    const nextBtn = card.querySelector(".detail-next");

    const prevOrderId = card.dataset.prevOrderId;
    const nextOrderId = card.dataset.nextOrderId;
    const prevRawHash = card.dataset.prevRawHash;
    const nextRawHash = card.dataset.nextRawHash;

    if (prevBtn) {
      if (prevRawHash || prevOrderId) {
        prevBtn.disabled = false;
        prevBtn.addEventListener("click", () => {
          if (prevRawHash) {
            loadDetailByHash(prevRawHash);
          } else {
          loadDetailByOrder(prevOrderId);
          }
        });
      } else {
        prevBtn.disabled = true;
      }
    }

    if (nextBtn) {
      if (nextRawHash || nextOrderId) {
        nextBtn.disabled = false;
        nextBtn.addEventListener("click", () => {
          if (nextRawHash) {
            loadDetailByHash(nextRawHash);
          } else {
          loadDetailByOrder(nextOrderId);
          }
        });
      } else {
        nextBtn.disabled = true;
      }
    }
  }

  function openDialogByProperty(propertyId, options = {}) {
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }

    modalBody.innerHTML = `<div class="modal-loading">Loading...</div>`;
    loadDetail(propertyId, options);
  }

  function openDialogByOrderId(orderId, options = {}) {
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }

    modalBody.innerHTML = `<div class="modal-loading">Loading...</div>`;
    loadDetailByOrder(orderId, options);
  }

  function openDialogByHash(rawHash, options = {}) {
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }

    modalBody.innerHTML = `<div class="modal-loading">Loading...</div>`;
    loadDetailByHash(rawHash, options);
  }

  function openDialogForRow(row) {
    const rawHash = row.dataset.rawHash;
    if (rawHash) {
      openDialogByHash(rawHash);
      return;
    }
    const orderId = row.dataset.orderId;
    if (orderId) {
      openDialogByOrderId(orderId);
      return;
    }
    const propertyId = row.dataset.propertyId;
    if (propertyId) {
      openDialogByProperty(propertyId);
    }
  }

  function closeDialog() {
    if (typeof dialog.close === "function") {
      dialog.close();
    } else {
      dialog.removeAttribute("open");
    }
    modalBody.innerHTML = "";
  }

  dialog.addEventListener("click", (event) => {
    if (event.target.classList.contains("modal-backdrop")) {
      closeDialog();
    }
  });

  document.addEventListener("click", (event) => {
    const trigger = event.target.closest(".detail-trigger");
    if (trigger) {
      const row = trigger.closest("tr.property-row");
      if (row) {
        openDialogForRow(row);
        event.stopPropagation();
      }
      return;
    }

    const clickableRow = event.target.closest("tr.property-row");
    if (clickableRow && !event.target.closest("a")) {
      openDialogForRow(clickableRow);
    }
  });

  window.openPropertyDetail = function ({ propertyId, orderId, rawHash, context } = {}) {
    const options = {};
    if (context) {
      options.context = context;
    }

    if (rawHash) {
      openDialogByHash(rawHash, options);
      return;
    }

    if (orderId) {
      openDialogByOrderId(orderId, options);
      return;
    }

    if (propertyId) {
      openDialogByProperty(propertyId, options);
    }
  };

  window.closePropertyDetail = closeDialog;
})();

