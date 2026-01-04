(function () {
  function formatElement(el) {
    const iso = el.getAttribute("datetime") || el.dataset.timestamp;
    if (!iso) {
      return;
    }

    const parsed = new Date(iso);
    if (Number.isNaN(parsed.getTime())) {
      return;
    }

    const options = {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    };

    el.textContent = parsed.toLocaleString(undefined, options);
  }

  function applyFormatting() {
    document
      .querySelectorAll(".js-local-time")
      .forEach((el) => formatElement(el));

  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyFormatting);
  } else {
    applyFormatting();
  }
})();

