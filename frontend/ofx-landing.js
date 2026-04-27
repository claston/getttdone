(function () {
  const yearNode = document.getElementById("footer-year");
  const topAuthLoginLink = document.getElementById("top-auth-login-link");
  const topAuthPrimaryLink = document.getElementById("top-auth-primary-link");
  const USER_TOKEN_KEY = "ofxsimples_user_token";
  if (yearNode) {
    yearNode.textContent = "(c) " + new Date().getFullYear() + " OFX Simples. Todos os direitos reservados.";
  }

  function resolveApiBase() {
    const host = window.location.hostname;
    const port = window.location.port;
    const isLocalHost = host === "localhost" || host === "127.0.0.1";
    const isDevFrontend = isLocalHost && port !== "8000";
    if (isDevFrontend) return "http://127.0.0.1:8000";
    if (window.location.origin && window.location.origin !== "null") return window.location.origin;
    return "http://127.0.0.1:8000";
  }

  function getUserToken() {
    const token = String(localStorage.getItem(USER_TOKEN_KEY) || "").trim();
    return token || null;
  }

  function clearUserToken() {
    localStorage.removeItem(USER_TOKEN_KEY);
  }

  function applyLoggedInTopState() {
    if (topAuthLoginLink) topAuthLoginLink.classList.add("hidden");
    if (topAuthPrimaryLink) {
      topAuthPrimaryLink.textContent = "Minha Conta";
      topAuthPrimaryLink.setAttribute("href", "./client-area.html");
    }
  }

  function applyLoggedOutTopState() {
    if (topAuthLoginLink) {
      topAuthLoginLink.classList.remove("hidden");
      topAuthLoginLink.setAttribute("href", "./login.html?next=%2Fofx-convert.html");
    }
    if (topAuthPrimaryLink) {
      topAuthPrimaryLink.textContent = "Converter agora";
      topAuthPrimaryLink.setAttribute("href", "./ofx-convert.html");
    }
  }

  async function getSessionValidationState(token) {
    if (!token) return "missing";
    try {
      const apiBase = resolveApiBase();
      const response = await fetch(`${apiBase}/auth/me?user_token=${encodeURIComponent(token)}`);
      if (response.ok) {
        return "valid";
      }
      if (response.status === 401) {
        return "invalid";
      }
      return "unknown";
    } catch (_error) {
      return "unknown";
    }
  }

  async function syncTopAuthBySession() {
    const token = getUserToken();
    if (!token) {
      applyLoggedOutTopState();
      return;
    }
    const sessionState = await getSessionValidationState(token);
    if (sessionState === "valid" || sessionState === "unknown") {
      applyLoggedInTopState();
      return;
    }
    clearUserToken();
    applyLoggedOutTopState();
  }

  const menuToggle = document.getElementById("menu-toggle");
  const topLinks = document.getElementById("top-links");
  if (menuToggle && topLinks) {
    menuToggle.addEventListener("click", function () {
      const open = topLinks.classList.toggle("is-open");
      menuToggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  void syncTopAuthBySession();
})();
