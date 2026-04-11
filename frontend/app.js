const DEFAULT_API_BASE = "http://127.0.0.1:8000";

const form = document.getElementById("analyze-form");
const fileInput = document.getElementById("file-input");
const apiBaseInput = document.getElementById("api-base");
const submitBtn = document.getElementById("submit-btn");
const errorNode = document.getElementById("error");
const resultNode = document.getElementById("result");
const statsNode = document.getElementById("stats");
const beforeAfterWrap = document.getElementById("before-after-wrap");
const beforeAfterBody = document.getElementById("before-after-body");
const previewBody = document.getElementById("preview-body");
const downloadLink = document.getElementById("download-link");
const apiStatus = document.getElementById("api-status");

function normalizeApiBase(value) {
  return (value || DEFAULT_API_BASE).replace(/\/+$/, "");
}

function formatCurrency(value) {
  return new Intl.NumberFormat("pt-BR", {
    style: "currency",
    currency: "BRL"
  }).format(Number(value || 0));
}

function setError(message) {
  if (!message) {
    errorNode.hidden = true;
    errorNode.textContent = "";
    return;
  }
  errorNode.hidden = false;
  errorNode.textContent = message;
}

function renderStats(data) {
  const operational = data.operational_summary || {};
  const metrics = [
    ["Transações", String(data.transactions_total)],
    ["Entradas", formatCurrency(data.total_inflows)],
    ["Saídas", formatCurrency(data.total_outflows)],
    ["Saldo", formatCurrency(data.net_total)],
    ["Volume Total", formatCurrency(operational.total_volume || 0)],
    ["Qtd Entradas", String(operational.inflow_count || 0)],
    ["Qtd Saídas", String(operational.outflow_count || 0)]
  ];

  statsNode.innerHTML = "";
  for (const [label, value] of metrics) {
    const item = document.createElement("div");
    item.className = "metric";
    const strong = document.createElement("strong");
    strong.textContent = label;
    const text = document.createElement("p");
    text.textContent = value;
    text.className = "muted";
    text.style.margin = "6px 0 0";
    item.append(strong, text);
    statsNode.appendChild(item);
  }
}

function renderPreviewRows(rows) {
  previewBody.innerHTML = "";
  for (const row of rows) {
    const tr = document.createElement("tr");
    const values = [
      row.date,
      row.description,
      formatCurrency(row.amount),
      row.category,
      row.reconciliation_status
    ];

    for (const value of values) {
      const td = document.createElement("td");
      td.textContent = String(value);
      tr.appendChild(td);
    }

    previewBody.appendChild(tr);
  }
}

function renderBeforeAfterRows(rows) {
  beforeAfterBody.innerHTML = "";
  const hasRows = Array.isArray(rows) && rows.length > 0;
  beforeAfterWrap.hidden = !hasRows;
  if (!hasRows) {
    return;
  }

  for (const row of rows) {
    const tr = document.createElement("tr");
    const values = [
      row.date,
      row.description_before,
      row.description_after,
      formatCurrency(row.amount_before),
      formatCurrency(row.amount_after)
    ];

    for (const value of values) {
      const td = document.createElement("td");
      td.textContent = String(value);
      tr.appendChild(td);
    }

    beforeAfterBody.appendChild(tr);
  }
}

async function checkApi() {
  const baseUrl = normalizeApiBase(apiBaseInput.value);
  try {
    const response = await fetch(`${baseUrl}/health`);
    if (!response.ok) {
      throw new Error(`Status ${response.status}`);
    }
    apiStatus.textContent = "API online";
  } catch (_error) {
    apiStatus.textContent = "API offline. Inicie o backend em http://127.0.0.1:8000";
  }
}

apiBaseInput.addEventListener("change", () => {
  const baseUrl = normalizeApiBase(apiBaseInput.value);
  localStorage.setItem("gettdone_api_base", baseUrl);
  apiBaseInput.value = baseUrl;
  checkApi();
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setError("");
  resultNode.hidden = true;

  if (!fileInput.files || !fileInput.files[0]) {
    setError("Selecione um arquivo CSV, XLSX ou OFX.");
    return;
  }

  const file = fileInput.files[0];
  const baseUrl = normalizeApiBase(apiBaseInput.value);
  const formData = new FormData();
  formData.append("file", file);

  submitBtn.disabled = true;
  submitBtn.textContent = "Processando...";

  try {
    const response = await fetch(`${baseUrl}/analyze`, {
      method: "POST",
      body: formData
    });

    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Falha ao processar arquivo.");
    }

    renderStats(payload);
    renderPreviewRows(payload.preview_transactions || []);
    renderBeforeAfterRows(payload.preview_before_after || []);
    downloadLink.href = `${baseUrl}/report/${payload.analysis_id}`;
    resultNode.hidden = false;
  } catch (error) {
    const message = error instanceof Error ? error.message : "Erro inesperado.";
    setError(message);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Analisar extrato";
  }
});

(function init() {
  const savedBase = localStorage.getItem("gettdone_api_base");
  apiBaseInput.value = normalizeApiBase(savedBase || DEFAULT_API_BASE);
  checkApi();
})();
