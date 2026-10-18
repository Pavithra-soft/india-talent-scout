const planFields = {
  must_have: document.querySelector("#must-have"),
  nice_to_have: document.querySelector("#nice-to-have"),
  titles: document.querySelector("#titles"),
  min_years: document.querySelector("#min-years"),
  max_years: document.querySelector("#max-years"),
  locations: document.querySelector("#locations"),
  notice: document.querySelector("#notice"),
};

function skillsText(entries) {
  return (entries || []).map((entry) => entry.skill || entry).join(", ");
}

function showPlan(plan) {
  planFields.must_have.value = skillsText(plan.must_have);
  planFields.nice_to_have.value = skillsText(plan.nice_to_have);
  planFields.titles.value = (plan.titles || []).join(", ");
  planFields.min_years.value = plan.min_years ?? "";
  planFields.max_years.value = plan.max_years ?? "";
  planFields.locations.value = (plan.locations || []).join(", ");
  planFields.notice.value = plan.notice || "";
  const queries = plan.queries || {};
  document.querySelector("#query-generic").value = queries.generic || "";
  document.querySelector("#query-naukri").value = queries.naukri || "";
  document.querySelector("#query-linkedin").value = queries.linkedin || "";
  document.querySelector("#query-indeed").value = queries.indeed || "";
  window.__searchPlan = plan;
}

function readPlan() {
  const base = window.__searchPlan || {};
  const split = (value) => value.split(",").map((part) => part.trim()).filter(Boolean);
  const entries = (value) => split(value).map((skill) => ({ skill, variants: [skill] }));
  return {
    must_have: entries(planFields.must_have.value),
    nice_to_have: entries(planFields.nice_to_have.value),
    titles: split(planFields.titles.value),
    min_years: planFields.min_years.value,
    max_years: planFields.max_years.value,
    locations: split(planFields.locations.value),
    notice: planFields.notice.value,
    queries: {
      generic: document.querySelector("#query-generic").value,
      naukri: document.querySelector("#query-naukri").value,
      linkedin: document.querySelector("#query-linkedin").value,
      indeed: document.querySelector("#query-indeed").value,
    },
    raw_titles: base.titles || [],
  };
}

const savedPlan = JSON.parse(document.querySelector("#saved-plan").textContent || "null");
if (savedPlan) {
  showPlan(savedPlan);
  document.querySelector("#approved").checked = Boolean(savedPlan.approved);
}

document.querySelector("#build-plan").addEventListener("click", async () => {
  const status = document.querySelector("#plan-status");
  status.textContent = "Building the plan…";
  const body = new FormData();
  body.set("jd_text", document.querySelector("#jd-text").value);
  let response = await fetch("/recruit/jd/portals/plan", { method: "POST", body });
  if (response.status === 409) {
    if (!confirm("Replace the current JD and its portal results?")) {
      status.textContent = "Plan was not replaced.";
      return;
    }
    body.set("confirm_replace", "1");
    response = await fetch("/recruit/jd/portals/plan", { method: "POST", body });
  }
  if (!response.ok) {
    status.textContent = "Could not build a plan.";
    return;
  }
  const payload = await response.json();
  showPlan(payload.plan);
  status.textContent = "Review the plan, then approve and save it before searching.";
});

document.querySelector("#plan-form").addEventListener("submit", () => {
  document.querySelector("#plan-json").value = JSON.stringify(readPlan());
});

document.querySelector("#search-form").addEventListener("submit", (event) => {
  if (!document.querySelector("#approved").checked) {
    event.preventDefault();
    document.querySelector("#plan-status").textContent = "Approve the plan before searching.";
    return;
  }
  document.querySelector("#search-plan-json").value = JSON.stringify(readPlan());
  document.querySelector("#search-jd-text").value = document.querySelector("#jd-text").value;
  let hidden = document.querySelector("#search-approved");
  if (!hidden) {
    hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = "approved";
    hidden.id = "search-approved";
    event.target.append(hidden);
  }
  hidden.value = "1";
});

document.querySelector("#select-all").addEventListener("click", () => {
  document.querySelectorAll("input[name=hit_ids]").forEach((box) => {
    box.checked = true;
  });
});

document.querySelector("#select-top").addEventListener("click", () => {
  const count = Number(document.querySelector("#top-n").value || 0);
  document.querySelectorAll("input[name=hit_ids]").forEach((box, index) => {
    box.checked = index < count;
  });
});

function selectedIds() {
  return [...document.querySelectorAll("input[name=hit_ids]:checked")].map((box) => box.value);
}

async function writeFiles(payload) {
  const total = payload.files.length || 1;
  let done = 0;
  const bar = document.querySelector("#progress-bar");
  if (!window.showDirectoryPicker) {
    return false;
  }
  const root = await window.showDirectoryPicker();
  let dir = root;
  if (payload.directory) {
    dir = await root.getDirectoryHandle(payload.directory, { create: true });
  }
  for (const file of payload.files) {
    const handle = await dir.getFileHandle(file.name, { create: true });
    const writable = await handle.createWritable();
    await writable.write(file.content);
    await writable.close();
    done += 1;
    bar.style.width = `${Math.round((done / total) * 100)}%`;
  }
  return true;
}

async function download(force) {
  const status = document.querySelector("#download-status");
  const ids = selectedIds();
  if (!ids.length) {
    status.textContent = "Select at least one profile.";
    return;
  }
  const body = new FormData();
  ids.forEach((id) => body.append("hit_ids", id));
  body.set("force", force ? "1" : "0");
  body.set("per_jd_folder", document.querySelector("#per-jd-folder").checked ? "1" : "0");
  const response = await fetch("/recruit/jd/portals/download", { method: "POST", body });
  if (!response.ok) {
    status.textContent = "Download failed.";
    return;
  }
  const payload = await response.json();
  let wrote = false;
  try {
    wrote = await writeFiles(payload);
  } catch (error) {
    if (error && error.name === "AbortError") {
      status.textContent = "Folder picker was cancelled.";
      return;
    }
    wrote = false;
  }
  if (!wrote) {
    const zip = await fetch("/recruit/jd/portals/download.zip", { method: "POST", body });
    const blob = await zip.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = "portal-profiles.zip";
    link.click();
  }
  const lines = payload.log.map((row) => `${row.status}: ${row.file} ${row.detail || ""}`);
  document.querySelector("#download-log").textContent = lines.join("\n");
  status.textContent = wrote ? "Files written to the chosen folder." : "ZIP download started.";
  document.querySelector("#progress-bar").style.width = "100%";
}

document.querySelector("#download-btn").addEventListener("click", () => download(false));
document.querySelector("#retry-btn").addEventListener("click", () => download(true));

document.querySelector("#analyze-btn").addEventListener("click", () => {
  const ids = selectedIds();
  const body = new FormData();
  ids.forEach((id) => body.append("hit_ids", id));
  fetch("/recruit/jd/portals/to-analysis", { method: "POST", body, redirect: "manual" }).then(() => {
    window.location = "/recruit/jd";
  });
});

document.querySelectorAll(".similar").forEach((button) => {
  button.addEventListener("click", () => {
    const body = new FormData();
    body.set("hit_id", button.dataset.id);
    fetch("/recruit/jd/portals/similar", { method: "POST", body, redirect: "manual" }).then(() => {
      window.location = "/recruit/jd/portals?message=Similar+profiles+added";
    });
  });
});
