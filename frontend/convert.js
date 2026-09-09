(function () {
  const topAuthLoginLink = document.getElementById("top-auth-login-link");
  const topAuthPrimaryLink = document.getElementById("top-auth-primary-link");
  const menuToggle = document.getElementById("menu-toggle");
  const topLinks = document.getElementById("top-links");
  const session = window.OfxSession;

  function renderLoggedInTop(email) {
    if (topAuthLoginLink) topAuthLoginLink.classList.add("hidden");
    if (topAuthPrimaryLink) {
      const safe = String(email || "conta").trim() || "conta";
      const initial = safe.charAt(0).toUpperCase();
      const avatar = document.createElement("span");
      avatar.className = "top-account-avatar";
      avatar.textContent = initial;
      const label = document.createElement("span");
      label.className = "top-account-email";
      label.textContent = safe;
      const caret = document.createElement("span");
      caret.className = "top-account-caret";
      caret.textContent = "▾";
      topAuthPrimaryLink.replaceChildren(avatar, label, caret);
      topAuthPrimaryLink.classList.add("top-account-trigger");
      topAuthPrimaryLink.setAttribute("href", "/client-area.html");
    }
  }

  function renderLoggedOutTop() {
    if (topAuthLoginLink) {
      topAuthLoginLink.classList.remove("hidden");
      topAuthLoginLink.setAttribute("href", "/login.html?next=%2Fconvert.html");
    }
    if (topAuthPrimaryLink) {
      topAuthPrimaryLink.textContent = "Converter agora";
      topAuthPrimaryLink.classList.remove("top-account-trigger");
      topAuthPrimaryLink.setAttribute("href", "/convert.html");
    }
  }

  async function syncTopAuthBySession() {
    try {
      const currentUser = session ? await session.getCurrentUser() : null;
      if (currentUser) renderLoggedInTop(currentUser.email);
      else renderLoggedOutTop();
    } catch (_error) {
      renderLoggedOutTop();
    }
  }

  if (menuToggle && topLinks) {
    menuToggle.addEventListener("click", function () {
      const open = topLinks.classList.toggle("is-open");
      menuToggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  void syncTopAuthBySession();
})();
