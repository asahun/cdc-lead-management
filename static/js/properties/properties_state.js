(() => {
  const STORAGE_KEY = "lead_app.properties.state";

  const storageAvailable = (() => {
    try {
      const testKey = "__lead_app_storage_test__";
      window.localStorage.setItem(testKey, "1");
      window.localStorage.removeItem(testKey);
      return true;
    } catch {
      return false;
    }
  })();

  if (!storageAvailable) {
    return;
  }

  const normalizePage = (value) => {
    if (!value) {
      return null;
    }
    const parsed = parseInt(value, 10);
    if (!Number.isFinite(parsed) || parsed <= 0) {
      return null;
    }
    return String(parsed);
  };

  const parseState = (raw) => {
    if (!raw) {
      return null;
    }
    try {
      const data = JSON.parse(raw);
      if (!data || typeof data !== "object") {
        return null;
      }
      const page = normalizePage(data.page) || "1";
      const q = typeof data.q === "string" ? data.q : "";
      return { page, q };
    } catch {
      return null;
    }
  };

  const saveState = (pageValue, queryValue) => {
    const page = normalizePage(pageValue) || "1";
    const q = typeof queryValue === "string" ? queryValue : "";
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ page, q }));
    } catch {
      // Ignore write errors silently (e.g., storage full).
    }
  };

  const params = new URLSearchParams(window.location.search);
  const currentPage = normalizePage(params.get("page"));
  const currentQuery = params.get("q") || "";
  const storedState = parseState(window.localStorage.getItem(STORAGE_KEY));

  if (storedState) {
    const desiredParams = new URLSearchParams(window.location.search);
    const storedPage = storedState.page;
    const storedQuery = storedState.q;
    let changed = false;

    if (storedQuery && desiredParams.get("q") !== storedQuery) {
      desiredParams.set("q", storedQuery);
      changed = true;
    }

    const desiredPage = normalizePage(desiredParams.get("page"));
    const shouldSetPage =
      storedPage &&
      ((desiredPage && desiredPage !== storedPage) ||
        (!desiredPage && (storedPage !== "1" || storedQuery)));

    if (shouldSetPage) {
      desiredParams.set("page", storedPage);
      changed = true;
    }

    if (changed) {
      const newSearch = desiredParams.toString();
      const newUrl = newSearch
        ? `${window.location.pathname}?${newSearch}`
        : window.location.pathname;
      if (newUrl !== window.location.href) {
        window.location.replace(newUrl);
        return;
      }
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const activeParams = new URLSearchParams(window.location.search);
    saveState(activeParams.get("page"), activeParams.get("q") || "");

    const pagerLinks = document.querySelectorAll(".pager-buttons a");
    pagerLinks.forEach((link) => {
      link.addEventListener("click", () => {
        try {
          const url = new URL(link.href, window.location.origin);
          saveState(url.searchParams.get("page"), url.searchParams.get("q") || "");
        } catch {
          // Ignore URL parsing errors.
        }
      });
    });

    const searchForm = document.querySelector("form.page-actions");
    if (searchForm) {
      searchForm.addEventListener("submit", () => {
        const formData = new FormData(searchForm);
        const value = formData.get("q");
        saveState("1", typeof value === "string" ? value : "");
      });
    }
  });
})();

