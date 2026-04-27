(function () {
  const profileEmail = document.getElementById("profile-email");
  const quotaText = document.getElementById("quota-text");
  const historyRows = document.getElementById("history-rows");
  const statusMsg = document.getElementById("status-msg");
  const logoutBtn = document.getElementById("logout-btn");
  const viewAllLink = document.getElementById("view-all-link");
  const USER_TOKEN_KEY = "ofxsimples_user_token";

  function resolveApiBase() {
    const host = window.location.hostname;
    const port = window.location.port;
    const isLocalHost = host === "localhost" || host === "127.0.0.1";
    const isDevFrontend = isLocalHost && port !== "8000";
    if (isDevFrontend) {
      return "http://127.0.0.1:8000";
    }
    if (window.location.origin && window.location.origin !== "null") {
      return window.location.origin;
    }
    return "http://127.0.0.1:8000";
  }

  const apiBase = resolveApiBase();

  function getUserToken() {
    const token = String(localStorage.getItem(USER_TOKEN_KEY) || "").trim();
    return token || null;
  }

  function clearUserToken() {
    localStorage.removeItem(USER_TOKEN_KEY);
  }

  function escapeHtml(value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function setStatus(message, kind) {
    statusMsg.textContent = message || "";
    statusMsg.className = "status-msg";
    if (kind) {
      statusMsg.classList.add(kind);
    }
  }

  function formatDate(value) {
    const raw = String(value || "").trim();
    if (!raw) {
      return "-";
    }

    const parsed = new Date(raw);
    if (Number.isNaN(parsed.getTime())) {
      return escapeHtml(raw);
    }

    const parts = new Intl.DateTimeFormat("en-GB", {
      day: "2-digit",
      month: "short",
      year: "numeric",
    }).formatToParts(parsed);

    const day = parts.find((part) => part.type === "day")?.value;
    const month = parts.find((part) => part.type === "month")?.value;
    const year = parts.find((part) => part.type === "year")?.value;

    if (!day || !month || !year) {
      return escapeHtml(raw);
    }

    return `${day} ${month}, ${year}`;
  }

  function normalizeStatus(status) {
    const raw = String(status || "").trim().toLowerCase();

    if (!raw) {
      return {
        label: "DESCONHECIDO",
        className: "status-processing",
      };
    }

    if (raw.includes("error") || raw.includes("erro") || raw.includes("fail")) {
      return {
        label: "ERRO",
        className: "status-error",
      };
    }

    if (raw.includes("process") || raw.includes("pending") || raw.includes("queue")) {
      return {
        label: "PROCESSANDO",
        className: "status-processing",
      };
    }

    return {
      label: "PRONTO",
      className: "status-ready",
    };
  }

  function resolveTransactions(item) {
    const possible = [
      item.transactions_count,
      item.transaction_count,
      item.total_transactions,
      item.transactions,
    ];

    for (const value of possible) {
      if (typeof value === "number" && Number.isFinite(value)) {
        return value;
      }
      if (typeof value === "string" && value.trim() !== "" && !Number.isNaN(Number(value))) {
        return Number(value);
      }
    }

    return null;
  }

  function renderRows(items) {
    if (!items || items.length === 0) {
      historyRows.innerHTML = '<tr><td colspan="4">Nenhuma conversao encontrada.</td></tr>';
      return;
    }

    historyRows.innerHTML = items
      .map((item) => {
        const normalizedStatus = normalizeStatus(item.status);
        const filename = escapeHtml(item.filename || "arquivo_sem_nome.ofx");
        const created = formatDate(item.created_at);
        const transactions = resolveTransactions(item);
        const txClass = typeof transactions === "number" && transactions > 0 ? "transactions-strong" : "transactions-dim";
        const txText = typeof transactions === "number" ? String(transactions) : "--";

        return `
          <tr>
            <td>
              <div class="file-cell">
                <span class="file-icon" aria-hidden="true">DOC</span>
                <span>${filename}</span>
              </div>
            </td>
            <td>${created}</td>
            <td class="${txClass}">${txText}</td>
            <td>
              <span class="status-chip ${normalizedStatus.className}">${normalizedStatus.label}</span>
            </td>
          </tr>
        `;
      })
      .join("");
  }

  async function fetchJson(url) {
    const response = await fetch(url);
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload.detail || "Falha ao carregar dados.");
    }
    return payload;
  }

  async function loadClientArea() {
    const token = getUserToken();
    if (!token) {
      window.location.href = "./login.html?next=%2Fclient-area.html";
      return;
    }

    try {
      const me = await fetchJson(`${apiBase}/auth/me?user_token=${encodeURIComponent(token)}`);
      const history = await fetchJson(`${apiBase}/client/conversions?user_token=${encodeURIComponent(token)}&limit=20`);

      profileEmail.textContent = me.email || "-";
      quotaText.textContent = `Cota restante: ${me.quota_remaining} / ${me.quota_limit}`;
      renderRows(history.items || []);
      setStatus("Historico carregado com sucesso.", null);

      if (viewAllLink && (!history.items || history.items.length < 20)) {
        viewAllLink.style.visibility = "hidden";
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Falha ao carregar area do cliente.";
      if (message.toLowerCase().includes("invalid user token")) {
        clearUserToken();
        window.location.href = "./login.html?next=%2Fclient-area.html";
        return;
      }
      setStatus(message, "error");
      historyRows.innerHTML = '<tr><td colspan="4">Nao foi possivel carregar as conversoes.</td></tr>';
    }
  }

  if (logoutBtn) {
    logoutBtn.addEventListener("click", () => {
      clearUserToken();
      window.location.href = "./ofx-convert.html?logout=1";
    });
  }

  void loadClientArea();
})();
