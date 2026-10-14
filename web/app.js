const state = { job: null, meta: null, token: sessionStorage.getItem("workspaceToken") || "" };

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[char]));
}

const stepper = document.querySelector("#stepper");
const uploadStatus = document.querySelector("#upload-status");
const summaryPanel = document.querySelector("#summary-panel");
const requestPanel = document.querySelector("#request-panel");
const planPanel = document.querySelector("#plan-panel");
const resultPanel = document.querySelector("#result-panel");
const tokenLabel = document.querySelector("#token-label");
const tokenInput = document.querySelector("#token-input");

const steps = [
  ["upload", "بارگذاری"],
  ["review", "بررسی"],
  ["plan", "طرح"],
  ["run", "اجرا"],
  ["download", "دریافت"],
];

function headers(extra = {}) {
  const result = { ...extra };
  if (state.token) result["X-Workspace-Token"] = state.token;
  return result;
}

async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...headers(), ...(options.headers || {}) } });
  const isJson = (response.headers.get("content-type") || "").includes("json");
  const body = isJson ? await response.json() : null;
  if (response.status === 401) {
    tokenLabel.hidden = false;
    throw new Error("دسترسی مجاز نیست. رمز فضای کار را وارد کنید.");
  }
  if (!response.ok) {
    throw new Error(body?.error?.message_fa || "درخواست ناموفق بود.");
  }
  return body;
}

function stepIndex(status) {
  if (!status) return 0;
  if (["uploaded", "validating", "profiling", "failed"].includes(status)) return 1;
  if (["awaiting_request", "clarification_required"].includes(status)) return 2;
  if (["plan_ready", "approval_required"].includes(status)) return 3;
  if (["executing", "verifying", "exporting", "validation_failed"].includes(status)) return 3;
  if (["completed", "completed_with_limitations"].includes(status)) return 4;
  if (status === "cancelled") return 1;
  return 0;
}

function renderStepper(status) {
  const current = stepIndex(status);
  stepper.innerHTML = steps.map((item, index) => {
    const cls = index < current ? "done" : index === current ? "current" : "";
    return `<li class="${cls}">${item[1]}</li>`;
  }).join("");
}

function statusLabel(status) {
  const labels = {
    awaiting_request: "فایل بررسی شد و منتظر درخواست است.",
    plan_ready: "طرح آماده اجراست.",
    clarification_required: "قبل از اجرا باید ابهام مشخص شود.",
    approval_required: "طرح عملیات حذفی دارد و به تأیید جدا نیاز دارد.",
    completed: "اجرا و وارسی نهایی موفق بود.",
    completed_with_limitations: "بخش‌های پشتیبانی‌شده انجام شد و محدودیت‌ها در گزارش است.",
    validation_failed: "وارسی نهایی رد شد. فایل نتیجه ارائه نمی‌شود.",
    failed: "کار ناموفق بود.",
    cancelled: "کار قبل از اجرا لغو شد.",
  };
  return labels[status] || status;
}

function renderSummary(job) {
  const profile = job.profile;
  if (!profile) {
    summaryPanel.hidden = false;
    document.querySelector("#summary").innerHTML = `<p class="error">${job.error?.message_fa || "بررسی فایل ناموفق بود."}</p>`;
    return;
  }
  summaryPanel.hidden = false;
  const warnings = (job.inspection?.warnings || []).map((item) => `<div class="warning">${esc(item.message_fa)}</div>`).join("");
  document.querySelector("#summary").innerHTML = `
    <p>${esc(statusLabel(job.status))} قالب تشخیص‌داده‌شده: <b>${esc(job.detected_format)}</b></p>
    <div class="grid">
      <div class="metric"><span>برگه</span><b>${profile.sheet_count}</b></div>
      <div class="metric"><span>ردیف کاملاً خالی</span><b>${profile.fully_empty_rows}</b></div>
      <div class="metric"><span>سلول دارای فاصله اضافه</span><b>${profile.whitespace_cells}</b></div>
      <div class="metric"><span>ردیف تکراری دقیق اضافه</span><b>${profile.exact_duplicate_extra_rows}</b></div>
    </div>
    ${warnings}
    <p>هش منبع: <code>${esc(job.source_sha256)}</code></p>
    <p>نگهداری تا: ${esc(job.expires_at)}</p>
  `;
  const box = document.querySelector("#suggestions");
  box.innerHTML = "";
  if (profile.suggested_request_fa) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "secondary";
    button.textContent = "گذاشتن پیشنهاد بر اساس همین آمار";
    button.addEventListener("click", () => {
      document.querySelector("#request-input").value = profile.suggested_request_fa;
    });
    box.appendChild(button);
  }
}

function renderPlan(job) {
  const plan = job.plan;
  if (!plan) {
    planPanel.hidden = true;
    return;
  }
  planPanel.hidden = false;
  const ops = (plan.operations || []).map((op) => {
    const preview = op.preview ? `<p>پیش‌نمایش واقعی: ${op.preview.affected_count} مورد، حل‌نشده: ${op.preview.unresolved_count}</p>` : "<p>پیش‌نمایش پس از رفع ابهام ساخته می‌شود.</p>";
    const risk = op.requires_approval ? "danger" : "warn";
    return `<article class="op"><span class="badge ${risk}">${esc(op.risk)}</span><h3>${esc(op.title_fa)}</h3><p>${esc(op.changes_fa)}</p><p>${esc(op.preserves_fa)}</p>${preview}</article>`;
  }).join("");
  const questions = (plan.clarifications || []).map((item) => {
    const options = item.options.map((option) => `<option value="${esc(option.value)}">${esc(option.label_fa)}</option>`).join("");
    return `<label>${item.question_fa}<select data-clarification="${item.id}"><option value="">انتخاب کنید</option>${options}</select></label>`;
  }).join("");
  const unsupported = (plan.unsupported || []).map((item) => `<div class="warning">${esc(item.message_fa)}</div>`).join("");
  const notes = (plan.notes_fa || []).map((item) => `<div class="warning">${esc(item)}</div>`).join("");
  const approval = plan.requires_approval ? `<label><input id="approve" type="checkbox"> حذف تکراری‌های دقیقاً یکسان را تأیید می‌کنم. اولین ردیف هر گروه می‌ماند.</label>` : "";
  document.querySelector("#plan").innerHTML = `
    <p>${esc(plan.summary_fa)}</p>
    <p>${esc(plan.ai_note_fa || "")}</p>
    ${notes}${unsupported}${ops}
    ${questions}
    ${approval}
    <div class="row">
      <button type="button" id="execute-button" ${plan.blocking ? "disabled" : ""}>اجرای همین طرح</button>
      <button type="button" class="secondary" id="cancel-button">لغو کار</button>
    </div>
  `;
  document.querySelector("#execute-button").addEventListener("click", executePlan);
  document.querySelector("#cancel-button").addEventListener("click", cancelJob);
}

function renderResult(job) {
  const terminal = ["completed", "completed_with_limitations", "validation_failed", "failed", "cancelled"].includes(job.status);
  if (!terminal) {
    resultPanel.hidden = true;
    return;
  }
  resultPanel.hidden = false;
  const report = job.result?.report;
    const checks = (job.result?.validation?.checks || []).map((check) => `<li>${check.ok ? "قبول" : "رد"} — ${esc(check.detail_fa)}</li>`).join("");
    const ops = (report?.operations || []).map((op) => `<li>${esc(op.title_fa)}: ${esc(op.affected_count)} مورد، حل‌نشده ${esc(op.unresolved_count)}</li>`).join("");
  const limits = (report?.limitations || []).map((item) => `<div class="warning">${esc(item)}</div>`).join("");
  const downloads = document.createElement("div");
  downloads.className = "row";
  const names = [];
  if (job.result?.output_ready) names.push(["output", "دانلود خروجی"]);
  if (job.result?.report_ready) names.push(["report", "دانلود گزارش"]);
  if (job.result?.ledger_ready) names.push(["ledger", "دانلود دفتر تغییرات"]);
  document.querySelector("#result").innerHTML = `
    <p>${esc(statusLabel(job.status))}</p>
    ${job.error ? `<p class="error">${esc(job.error.message_fa)}</p>` : ""}
    ${limits}
    <ul>${ops}</ul>
    <ul>${checks}</ul>
  `;
  names.forEach(([name, label]) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.addEventListener("click", () => downloadArtifact(name));
    downloads.appendChild(button);
  });
  document.querySelector("#result").appendChild(downloads);
}

function showJob(job) {
  state.job = job;
  renderStepper(job.status);
  uploadStatus.textContent = statusLabel(job.status);
  renderSummary(job);
  const editable = ["awaiting_request", "plan_ready", "clarification_required", "approval_required", "failed", "validation_failed"].includes(job.status) && job.profile;
  requestPanel.hidden = !editable;
  renderPlan(job);
  renderResult(job);
}

async function downloadArtifact(name) {
  const response = await fetch(`/api/jobs/${state.job.id}/artifacts/${name}`, { headers: headers() });
  if (!response.ok) {
    const body = await response.json();
    uploadStatus.textContent = body.error?.message_fa || "دانلود ممکن نیست.";
    return;
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename\*=UTF-8''([^;]+)/);
  link.href = url;
  link.download = match ? decodeURIComponent(match[1]) : name;
  link.click();
  URL.revokeObjectURL(url);
}

async function upload(file) {
  uploadStatus.textContent = "در حال فرستادن فایل…";
  const body = new FormData();
  body.append("file", file, file.name);
  const data = await new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/jobs");
    if (state.token) xhr.setRequestHeader("X-Workspace-Token", state.token);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) uploadStatus.textContent = `فرستادن فایل: ${event.loaded} از ${event.total} بایت`;
    };
    xhr.onload = () => {
      const payload = JSON.parse(xhr.responseText || "{}");
      if (xhr.status >= 200 && xhr.status < 300) resolve(payload);
      else reject(new Error(payload.error?.message_fa || "بارگذاری ناموفق بود."));
    };
    xhr.onerror = () => reject(new Error("ارتباط با سرور قطع شد."));
    xhr.send(body);
  });
  uploadStatus.textContent = "پاسخ سرور دریافت شد.";
  showJob(data);
}

document.querySelector("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = document.querySelector("#file-input").files[0];
  if (!file) {
    uploadStatus.textContent = "ابتدا یک فایل انتخاب کنید.";
    return;
  }
  try { await upload(file); } catch (error) { uploadStatus.textContent = error.message; }
});

document.querySelector("#sample-button").addEventListener("click", async () => {
  const response = await fetch("/examples/customers.csv");
  const blob = await response.blob();
  await upload(new File([blob], "customers.csv", { type: "text/csv" }));
});

document.querySelector("#plan-button").addEventListener("click", async () => {
  const request = document.querySelector("#request-input").value.trim();
  if (!request || !state.job) return;
  const clarifications = {};
  document.querySelectorAll("[data-clarification]").forEach((select) => {
    if (select.value) clarifications[select.dataset.clarification] = select.value;
  });
  uploadStatus.textContent = "در حال ساخت طرح روی سرور…";
  try {
    const job = await api(`/api/jobs/${state.job.id}/plan`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request, clarifications }),
    });
    showJob(job);
  } catch (error) {
    uploadStatus.textContent = error.message;
  }
});

async function executePlan() {
  const plan = state.job?.plan;
  if (!plan) return;
  const approve = document.querySelector("#approve")?.checked || false;
  uploadStatus.textContent = "درخواست اجرا فرستاده شد. تا پاسخ سرور صبر می‌کنیم.";
  try {
    const job = await api(`/api/jobs/${state.job.id}/execute`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ plan_id: plan.id, approve_destructive: approve }),
    });
    showJob(job);
  } catch (error) {
    uploadStatus.textContent = error.message;
  }
}

async function cancelJob() {
  try {
    showJob(await api(`/api/jobs/${state.job.id}/cancel`, { method: "POST" }));
  } catch (error) {
    uploadStatus.textContent = error.message;
  }
}

tokenInput.addEventListener("change", () => {
  state.token = tokenInput.value.trim();
  if (state.token) sessionStorage.setItem("workspaceToken", state.token);
  else sessionStorage.removeItem("workspaceToken");
});

async function boot() {
  renderStepper(null);
  try {
    state.meta = await api("/api/meta");
    document.querySelector("#ai-note").textContent = state.meta.ai_note_fa;
    document.querySelector("#limits").textContent = `حداکثر ${state.meta.max_upload_bytes} بایت، ${state.meta.max_rows} ردیف، نگهداری ${state.meta.retention_hours} ساعت.`;
    tokenLabel.hidden = !state.meta.auth_required;
    if (state.token) tokenInput.value = state.token;
  } catch (error) {
    uploadStatus.textContent = error.message;
  }
}

boot();
