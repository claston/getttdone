(function () {
  const profileName = document.getElementById("profile-name");
  const profileEmail = document.getElementById("profile-email");
  const profileAvatar = document.getElementById("profile-avatar");
  const quotaText = document.getElementById("quota-text");
  const historyRows = document.getElementById("history-rows");
  const statusMsg = document.getElementById("status-msg");
  const logoutBtn = document.getElementById("logout-btn");

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
    const raw = localStorage.getItem("gettdone_user_token");
    const token = String(raw || "").trim();
    return token || null;
  }

  function clearUserToken() {
    localStorage.removeItem("gettdone_user_token");
  }

  function setStatus(message, kind) {
    statusMsg.textContent = message || "";
    statusMsg.className = "status";
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
      return raw;
    }
    return new Intl.DateTimeFormat("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(parsed);
  }

  function renderRows(items) {
    if (!items || items.length === 0) {
      historyRows.innerHTML = '<tr><td colspan="5">Nenhuma conversão encontrada.</td></tr>';
      return;
    }

    historyRows.innerHTML = items
      .map(
        (item) => `
        <tr>
          <td>${formatDate(item.created_at)}</td>
          <td>${item.filename || "-"}</td>
          <td>${item.model || "-"}</td>
          <td>${item.conversion_type || "-"}</td>
          <td><span class="badge-success">${item.status || "-"}</span></td>
        </tr>
      `,
      )
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

      profileName.textContent = me.name || "Usuário";
      profileEmail.textContent = me.email || "-";
      profileAvatar.textContent = (me.name || "U").trim().slice(0, 1).toUpperCase();
      quotaText.textContent = `Cota restante: ${me.quota_remaining} / ${me.quota_limit}`;
      renderRows(history.items || []);
      setStatus("Histórico carregado com sucesso.", null);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Falha ao carregar área do cliente.";
      if (message.toLowerCase().includes("invalid user token")) {
        clearUserToken();
        window.location.href = "./login.html?next=%2Fclient-area.html";
        return;
      }
      setStatus(message, "error");
    }
  }

  if (logoutBtn) {
    logoutBtn.addEventListener("click", () => {
      clearUserToken();
      window.location.href = "./login.html?next=%2Fofx-convert.html";
    });
  }

  void loadClientArea();
})();
