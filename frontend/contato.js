(function () {
  const topAuthLoginLink = document.getElementById("top-auth-login-link");
  const topAuthPrimaryLink = document.getElementById("top-auth-primary-link");
  const session = window.OfxSession;
  const form = document.getElementById("contact-form");
  const feedback = document.getElementById("contact-feedback");
  if (!form || !feedback) return;

  const submitButton = form.querySelector('button[type="submit"]');

  const apiBase = session ? session.apiBase : window.location.origin;

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
      topAuthPrimaryLink.setAttribute("href", "./client-area.html");
    }
  }

  function renderLoggedOutTop() {
    if (topAuthLoginLink) {
      topAuthLoginLink.classList.remove("hidden");
      topAuthLoginLink.setAttribute("href", "./login.html?next=%2Fofx-convert.html");
    }
    if (topAuthPrimaryLink) {
      topAuthPrimaryLink.textContent = "Converter agora";
      topAuthPrimaryLink.classList.remove("top-account-trigger");
      topAuthPrimaryLink.setAttribute("href", "./ofx-convert.html");
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

  function setFeedback(message, kind) {
    feedback.textContent = message || "";
    feedback.classList.remove("error", "success");
    if (kind) feedback.classList.add(kind);
  }

  function setSubmitting(isSubmitting) {
    if (!submitButton) return;
    submitButton.disabled = isSubmitting;
    submitButton.textContent = isSubmitting ? "Enviando..." : "Enviar Mensagem";
  }

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const name = String(document.getElementById("name").value || "").trim();
    const email = String(document.getElementById("email").value || "").trim();
    const subject = String(document.getElementById("subject").value || "").trim();
    const message = String(document.getElementById("message").value || "").trim();
    const attachmentInput = document.getElementById("attachment");
    const attachment = attachmentInput && attachmentInput.files ? attachmentInput.files[0] : null;

    if (!name || !email || !subject || !message) {
      setFeedback("Preencha nome, e-mail, assunto e mensagem.", "error");
      return;
    }

    setSubmitting(true);
    setFeedback("Enviando sua mensagem...", null);

    const formData = new FormData();
    formData.append("name", name);
    formData.append("email", email);
    formData.append("subject", subject);
    formData.append("message", message);
    if (attachment) formData.append("attachment", attachment);

    try {
      const response = await fetch(`${apiBase}/contact`, { method: "POST", body: formData });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        setFeedback(String(payload.detail || "Não foi possível enviar a mensagem agora."), "error");
        return;
      }
      if (payload.delivery_mode === "dry_run") {
        setFeedback("Mensagem registrada em modo de teste. Configure o provedor de e-mail para o envio real.", "success");
      } else {
        setFeedback("Mensagem enviada com sucesso. Nossa equipe vai responder no seu e-mail.", "success");
      }
      form.reset();
    } catch (_error) {
      setFeedback("Falha de rede ao enviar a mensagem. Tente novamente em instantes.", "error");
    } finally {
      setSubmitting(false);
    }
  });

  void syncTopAuthBySession();
})();
