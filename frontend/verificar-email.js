(function () {
  const PENDING_EMAIL_KEY = "ofxsimples_pending_verification_email";
  const PENDING_DELIVERY_KEY = "ofxsimples_pending_verification_delivery";
  const statusMsg = document.getElementById("status-msg");
  const description = document.getElementById("verification-description");
  const resendForm = document.getElementById("resend-form");
  const resendBtn = document.getElementById("resend-btn");
  const emailInput = document.getElementById("email");

  function resolveApiBase() {
    const host = window.location.hostname;
    const port = window.location.port;
    const isLocalHost = host === "localhost" || host === "127.0.0.1";
    if (isLocalHost && port !== "8000") return "http://127.0.0.1:8000";
    if (window.location.origin && window.location.origin !== "null") return window.location.origin;
    return "http://127.0.0.1:8000";
  }

  function setStatus(message, kind) {
    if (!(statusMsg instanceof HTMLElement)) return;
    statusMsg.textContent = message || "";
    statusMsg.className = "status";
    if (kind) statusMsg.classList.add(kind);
  }

  function showResendForm() {
    if (resendForm instanceof HTMLElement) resendForm.classList.remove("hidden");
  }

  function readFragmentToken() {
    const fragment = String(window.location.hash || "").replace(/^#/, "");
    return String(new URLSearchParams(fragment).get("token") || "").trim();
  }

  async function confirmToken(token) {
    setStatus("Confirmando seu e-mail...", null);
    const response = await fetch(`${resolveApiBase()}/auth/email-verification/confirm`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ token: token }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data && data.detail;
      const message = detail && typeof detail === "object" ? detail.message : detail;
      throw new Error(message || "Não foi possível confirmar este link.");
    }
  }

  async function resend(email) {
    const response = await fetch(`${resolveApiBase()}/auth/email-verification/resend`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ email: email }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error("Não foi possível solicitar um novo envio.");
    return data;
  }

  function startResendCooldown(seconds) {
    if (!(resendBtn instanceof HTMLButtonElement)) return;
    let remaining = seconds;
    resendBtn.disabled = true;
    resendBtn.textContent = `Reenviar em ${remaining}s`;
    const timer = window.setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        window.clearInterval(timer);
        resendBtn.disabled = false;
        resendBtn.textContent = "Reenviar confirmação";
        return;
      }
      resendBtn.textContent = `Reenviar em ${remaining}s`;
    }, 1000);
  }

  if (resendForm) {
    resendForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!(emailInput instanceof HTMLInputElement) || !emailInput.value.trim()) return;
      try {
        setStatus("Solicitando um novo envio...", null);
        const data = await resend(emailInput.value.trim());
        setStatus(data.message || "Se a conta estiver pendente, enviaremos uma nova mensagem.", "success");
        startResendCooldown(60);
      } catch (error) {
        setStatus(error instanceof Error ? error.message : "Falha ao reenviar a confirmação.", "error");
      }
    });
  }

  async function bootstrap() {
    const token = readFragmentToken();
    if (token) {
      window.history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
      try {
        await confirmToken(token);
        sessionStorage.removeItem(PENDING_EMAIL_KEY);
        sessionStorage.removeItem(PENDING_DELIVERY_KEY);
        if (description instanceof HTMLElement) description.textContent = "Sua conta está pronta para uso.";
        setStatus("E-mail confirmado com sucesso. Agora você pode entrar.", "success");
      } catch (error) {
        if (description instanceof HTMLElement) description.textContent = "O link não pôde ser confirmado.";
        setStatus(error instanceof Error ? error.message : "Link inválido ou expirado.", "error");
        showResendForm();
      }
      return;
    }

    const pendingEmail = String(sessionStorage.getItem(PENDING_EMAIL_KEY) || "").trim();
    const deliveryStatus = String(sessionStorage.getItem(PENDING_DELIVERY_KEY) || "").trim();
    if (emailInput instanceof HTMLInputElement) emailInput.value = pendingEmail;
    if (description instanceof HTMLElement) {
      description.textContent = "Enviamos um link de confirmação para o seu e-mail.";
    }
    if (deliveryStatus === "failed") {
      setStatus("A conta foi criada, mas o primeiro envio falhou. Solicite uma nova mensagem.", "error");
    } else {
      setStatus("Abra a mensagem recebida e use o link para liberar sua conta.", null);
    }
    showResendForm();
  }

  void bootstrap();
})();
