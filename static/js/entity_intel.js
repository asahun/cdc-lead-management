(function () {
  const button = document.getElementById("run-entity-intel");
  const resultContainer = document.getElementById("entity-intel-result");
  const progressText = document.getElementById("entity-intel-progress");

  if (!button || !resultContainer || !progressText) {
    return;
  }

  function formatAddress(address) {
    if (!address) {
      return "—";
    }

    const lines = [address.line1, address.line2].filter(Boolean);
    const cityLine = [address.city, address.state, address.postal_code]
      .filter(Boolean)
      .join(", ");

    if (cityLine) {
      lines.push(cityLine);
    }

    return lines.length ? lines.join("<br>") : "—";
  }

  function buildConfidencePill(confidence) {
    if (!confidence) {
      return "";
    }
    const level = confidence.toLowerCase();
    return `<span class="confidence-pill confidence-${level}">${confidence}</span>`;
  }

  function renderResult(data) {
    if (!data || !data.analysis) {
      resultContainer.classList.add("error-state");
      resultContainer.innerHTML = "No insights returned. Try again later.";
      return;
    }

    const analysis = data.analysis;
    const original = analysis.original_entity || {};
    const successor = analysis.successor_entity || {};
    const legal = analysis.legal_right_for_property || {};
    const claimant = legal.recommended_claimant || {};

    resultContainer.classList.remove("empty-state", "error-state");
    resultContainer.innerHTML = `
      <div class="intel-summary">
        <div>
          <h3>Original Entity</h3>
          <p class="intel-value">${original.legal_name ?? "—"}</p>
          <p class="intel-meta">Status: ${original.status ?? "unknown"}</p>
        </div>
        <div>
          <h3>Successor Entity</h3>
          <p class="intel-value">${successor.legal_name ?? "—"}</p>
          <p class="intel-meta">
            Status: ${successor.status ?? "unknown"}
            ${buildConfidencePill(successor.confidence)}
          </p>
        </div>
      </div>

      <div class="intel-details">
        <h3>Recommended Claimant</h3>
        <dl>
          <div>
            <dt>Entity Name</dt>
            <dd>
              ${claimant.entity_name ?? "—"}
              ${buildConfidencePill(claimant.confidence)}
            </dd>
          </div>
          <div>
            <dt>Reason</dt>
            <dd>${claimant.reason ?? "—"}</dd>
          </div>
          <div>
            <dt>Business Site</dt>
            <dd>
              ${
                claimant.business_site
                  ? `<a href="${claimant.business_site}" target="_blank" rel="noopener">${claimant.business_site}</a>`
                  : "—"
              }
            </dd>
          </div>
          <div>
            <dt>Mailing Address</dt>
            <dd>${formatAddress(claimant.mailing_address)}</dd>
          </div>
          <div>
            <dt>Physical Address</dt>
            <dd>${formatAddress(claimant.physical_address)}</dd>
          </div>
        </dl>
      </div>
    `;
  }

  async function handleClick() {
    const endpoint = button.dataset.endpoint;
    if (!endpoint) {
      return;
    }

    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    progressText.hidden = false;
    resultContainer.classList.remove("error-state");
    if (!resultContainer.classList.contains("empty-state")) {
      resultContainer.innerHTML = "";
    }

    try {
      const response = await fetch(endpoint, {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) {
        throw new Error(`Request failed (${response.status})`);
      }
      const data = await response.json();
      renderResult(data);
    } catch (error) {
      console.error("Entity intel fetch failed", error);
      resultContainer.classList.add("error-state");
      resultContainer.innerHTML = "Unable to load GPT insights. Please try again.";
    } finally {
      progressText.hidden = true;
      button.disabled = false;
      button.removeAttribute("aria-busy");
    }
  }

  button.addEventListener("click", handleClick);
})();

