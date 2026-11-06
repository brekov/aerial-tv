/* Aerial Study Guard admin UI — vanilla JS, no build step, no CDN. */
(() => {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  function toast(message, kind = "ok") {
    const host = $("#toasts");
    if (!host) return;
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.textContent = message;
    host.appendChild(el);
    setTimeout(() => el.remove(), kind === "error" ? 7000 : 3500);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  async function api(path, options = {}) {
    const init = { ...options, headers: { ...(options.headers || {}) } };
    if (init.body && !(init.body instanceof FormData)) {
      init.headers["Content-Type"] = "application/json";
      if (typeof init.body !== "string") init.body = JSON.stringify(init.body);
    }
    const response = await fetch(path, init);
    if (response.status === 401) {
      window.location.href = "/admin/login";
      throw new Error("not signed in");
    }
    let data = null;
    try {
      data = await response.json();
    } catch (err) {
      data = null;
    }
    if (!response.ok) {
      const detail = (data && (data.detail || data.error)) || `HTTP ${response.status}`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
  }

  function reloadSoon(delay = 500) {
    setTimeout(() => window.location.reload(), delay);
  }

  // ---------------------------------------------------------------- materials
  const uploadForm = $("#upload-form");
  if (uploadForm) {
    uploadForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const form = new FormData(uploadForm);
      if (!form.get("file") || !form.get("file").size) {
        toast("Choose an image first", "error");
        return;
      }
      try {
        const data = await api("/api/v1/admin/materials", { method: "POST", body: form });
        toast(data.deduplicated ? "Already uploaded (same sha256)" : "Material uploaded");
        reloadSoon(350);
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  // -------------------------------------------------------- manual questions
  const manualForm = $("#manual-question-form");
  if (manualForm) {
    manualForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(manualForm).entries());
      data.difficulty = Number(data.difficulty || 1);
      try {
        await api("/api/v1/admin/questions", { method: "POST", body: data });
        toast("Draft question created");
        reloadSoon(350);
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }

  // --------------------------------------------------------------- generation
  const generateForm = $("#generate-form");
  if (generateForm) {
    generateForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(generateForm).entries());
      if (!data.materialId) {
        toast("Upload an image first", "error");
        return;
      }
      data.count = Number(data.count || 5);
      const resultEl = $("#generate-result");
      resultEl.textContent = "Starting generation…";
      try {
        const response = await api("/api/v1/admin/generate", { method: "POST", body: data });
        const job = response.job;
        resultEl.textContent = `Job ${job.id} is ${job.status}.`;
        if (job.status === "failed") {
          toast(job.error || "Generation failed", "error");
          return;
        }
        toast("Generation job queued (draft questions only)");
        // Poll a few times so the admin sees the result without manual refresh.
        let attempts = 0;
        const timer = setInterval(async () => {
          attempts += 1;
          try {
            const latest = await api(`/api/v1/admin/jobs/${job.id}`);
            resultEl.textContent = `Job ${job.id}: ${latest.job.status}`;
            if (["succeeded", "failed"].includes(latest.job.status) || attempts > 40) {
              clearInterval(timer);
              if (latest.job.status === "succeeded") {
                toast(`Generated ${latest.job.questionIds.length} draft question(s)`);
              } else if (latest.job.status === "failed") {
                toast(latest.job.error || "Generation failed", "error");
              }
              reloadSoon(900);
            }
          } catch (err) {
            clearInterval(timer);
            toast(err.message, "error");
          }
        }, 1500);
      } catch (err) {
        resultEl.textContent = "";
        toast(err.message, "error");
      }
    });
  }

  // ------------------------------------------------------------ question edit
  const editForm = $("#edit-question-form");
  const revisionPanel = $("#revision-panel");
  const editCancel = $("#edit-cancel");
  const revisionClose = $("#revision-close");
  const sessionPanel = $("#session-panel");
  const sessionClose = $("#session-close");

  async function openEdit(questionId) {
    try {
      const data = await api(`/api/v1/admin/questions/${questionId}`);
      const question = data.question;
      editForm.elements.id.value = question.id;
      editForm.elements.prompt.value = question.prompt;
      editForm.elements.answer.value = question.answer;
      editForm.elements.imageId.value = question.imageId || "";
      editForm.elements.lang.value = question.lang;
      editForm.elements.difficulty.value = question.difficulty;
      editForm.elements.status.value = question.status;
      editForm.elements.changeNote.value = "";
      $("#edit-question-id").textContent = `#${question.id} (revision ${question.revision})`;
      editForm.hidden = false;
      editForm.scrollIntoView({ behavior: "smooth", block: "center" });
    } catch (err) {
      toast(err.message, "error");
    }
  }

  if (editForm) {
    editForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = Object.fromEntries(new FormData(editForm).entries());
      const id = data.id;
      delete data.id;
      data.difficulty = Number(data.difficulty || 1);
      if (!data.imageId) data.imageId = null;
      try {
        await api(`/api/v1/admin/questions/${id}`, { method: "PATCH", body: data });
        toast(`Question #${id} updated (new revision)`);
        reloadSoon(350);
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }
  editCancel?.addEventListener("click", () => { editForm.hidden = true; });

  async function openHistory(questionId) {
    try {
      const data = await api(`/api/v1/admin/questions/${questionId}/revisions`);
      const tbody = $("#revision-table tbody");
      tbody.innerHTML = data.revisions.map((revision) => `
        <tr>
          <td class="mono">${escapeHtml(revision.revision)}</td>
          <td>${escapeHtml(revision.prompt)}</td>
          <td>${escapeHtml(revision.answer)}</td>
          <td><span class="badge status-${escapeHtml(revision.status)}">${escapeHtml(revision.status)}</span></td>
          <td>${escapeHtml(revision.source)}</td>
          <td>${escapeHtml(revision.changedBy)}</td>
          <td>${escapeHtml(revision.changeNote)}</td>
          <td class="mono small">${escapeHtml(revision.createdAt)}</td>
        </tr>`).join("");
      revisionPanel.hidden = false;
      revisionPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
      toast(err.message, "error");
    }
  }
  revisionClose?.addEventListener("click", () => { revisionPanel.hidden = true; });

  async function setStatus(questionId, status, note) {
    try {
      await api(`/api/v1/admin/questions/${questionId}/status`, {
        method: "POST",
        body: { status, note },
      });
      toast(`Question #${questionId} -> ${status}`);
      reloadSoon(350);
    } catch (err) {
      toast(err.message, "error");
    }
  }

  // -------------------------------------------------------------- sessions
  async function openSession(sessionId) {
    try {
      const data = await api(`/api/v1/admin/sessions/${sessionId}`);
      const attempts = data.attempts || [];
      $("#session-detail").innerHTML = `
        <p class="small">
          status <strong>${escapeHtml(data.session.status)}</strong> ·
          progress ${data.progress.currentIndex}/${data.progress.total} ·
          correct ${data.progress.correct} · wrong ${data.progress.wrong} ·
          restarts ${data.progress.restarts} ·
          expires ${escapeHtml(data.session.expiresAt)}
        </p>
        <div class="table-wrap"><table class="table compact">
          <thead><tr><th>#</th><th>Question</th><th>Transcript</th><th>Correct</th><th>Method</th><th>At</th></tr></thead>
          <tbody>${attempts.map((attempt) => `
            <tr>
              <td class="mono">${escapeHtml(attempt.attemptNo)}</td>
              <td>${escapeHtml(attempt.questionPrompt || attempt.questionId)}</td>
              <td>${escapeHtml(attempt.transcript)}</td>
              <td>${attempt.correct ? "yes" : "no"}</td>
              <td>${escapeHtml(attempt.judgeMethod)}</td>
              <td class="mono small">${escapeHtml(attempt.createdAt)}</td>
            </tr>`).join("")}</tbody>
        </table></div>`;
      sessionPanel.hidden = false;
      sessionPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
    } catch (err) {
      toast(err.message, "error");
    }
  }
  sessionClose?.addEventListener("click", () => { sessionPanel.hidden = true; });

  // -------------------------------------------------------------- delegated
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-action]");
    if (!button) return;
    const id = button.dataset.id;
    switch (button.dataset.action) {
      case "edit": openEdit(id); break;
      case "history": openHistory(id); break;
      case "activate": setStatus(id, "active", "activated in admin"); break;
      case "review": setStatus(id, "reviewed", "reviewed in admin"); break;
      case "disable": setStatus(id, "disabled", "disabled in admin"); break;
      case "session": openSession(id); break;
      default: break;
    }
  });

  // --------------------------------------------------------------- providers
  $$("[data-provider-form]").forEach((form) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const name = form.dataset.providerForm;
      const data = Object.fromEntries(new FormData(form).entries());
      try {
        await api(`/api/v1/admin/providers/${name}`, { method: "PUT", body: data });
        toast(`${name} routing saved`);
        reloadSoon(400);
      } catch (err) {
        toast(err.message, "error");
      }
    });
  });

  const settingsForm = $("#settings-form");
  if (settingsForm) {
    settingsForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const formData = new FormData(settingsForm);
      const body = {
        defaultProvider: formData.get("defaultProvider"),
        aiJudgeEnabled: formData.get("aiJudgeEnabled") === "on",
      };
      try {
        await api("/api/v1/admin/settings", { method: "PUT", body });
        toast("Settings saved");
        reloadSoon(400);
      } catch (err) {
        toast(err.message, "error");
      }
    });
  }
})();
