(function () {
  const root = document.getElementById("jd-app");
  if (!root) return;
  const statusNode = document.getElementById("upload-status");
  const bar = document.getElementById("progress-bar");
  const rankStatus = document.getElementById("rank-status");

  function hasProfiles() {
    return root.dataset.hasProfiles === "1";
  }

  async function uploadAll(fileList) {
    const files = Array.from(fileList || []).filter((file) => file && file.size >= 0);
    if (!files.length) {
      statusNode.textContent = "No files found.";
      return;
    }
    const replacing = hasProfiles();
    if (replacing && !window.confirm("Replace the profiles already loaded?")) return;
    let confirmReplace = replacing ? "0" : "0";
    let added = 0;
    const errors = [];
    const size = 15;
    for (let offset = 0; offset < files.length; offset += size) {
      const chunk = files.slice(offset, offset + size);
      const body = new FormData();
      chunk.forEach((file) => body.append("files", file, file.name));
      body.append("replace", replacing && offset === 0 ? "1" : "0");
      body.append("confirm_replace", offset === 0 ? confirmReplace : "0");
      let response = await fetch("/recruit/jd/upload", { method: "POST", body });
      if (response.status === 409 && offset === 0) {
        confirmReplace = "1";
        body.set("confirm_replace", "1");
        response = await fetch("/recruit/jd/upload", { method: "POST", body });
      }
      const payload = await response.json();
      if (!response.ok) {
        errors.push(payload.detail || payload.message || "Upload failed.");
        break;
      }
      added += payload.added || 0;
      (payload.errors || []).forEach((item) => errors.push(item));
      const done = Math.min(files.length, offset + chunk.length);
      bar.style.width = Math.round((done / files.length) * 100) + "%";
      statusNode.textContent = "Uploaded " + done + " of " + files.length + " files.";
    }
    statusNode.textContent = "Added " + added + " profiles. " + errors.slice(0, 8).join(" ");
    if (added) window.location.reload();
  }

  async function filesFromDirectory(handle) {
    const found = [];
    for await (const [, entry] of handle.entries()) {
      if (entry.kind === "file") found.push(await entry.getFile());
      else if (entry.kind === "directory") found.push(...(await filesFromDirectory(entry)));
    }
    return found;
  }

  document.getElementById("pick-folder").addEventListener("click", async () => {
    if (!window.showDirectoryPicker) {
      document.getElementById("pick-files").click();
      return;
    }
    const handle = await window.showDirectoryPicker();
    await uploadAll(await filesFromDirectory(handle));
  });

  document.getElementById("pick-files").addEventListener("change", (event) => {
    uploadAll(event.target.files);
  });

  const zone = document.getElementById("drop-zone");
  zone.addEventListener("dragover", (event) => event.preventDefault());
  zone.addEventListener("drop", async (event) => {
    event.preventDefault();
    const files = [];
    const items = event.dataTransfer.items || [];
    const walks = [];
    for (const item of items) {
      const entry = item.webkitGetAsEntry && item.webkitGetAsEntry();
      if (entry) walks.push(walkEntry(entry, files));
      else if (item.getAsFile()) files.push(item.getAsFile());
    }
    await Promise.all(walks);
    if (!files.length && event.dataTransfer.files) {
      await uploadAll(event.dataTransfer.files);
      return;
    }
    await uploadAll(files);
  });

  async function walkEntry(entry, files) {
    if (entry.isFile) {
      files.push(await new Promise((resolve) => entry.file(resolve)));
      return;
    }
    if (!entry.isDirectory) return;
    const reader = entry.createReader();
    while (true) {
      const batch = await new Promise((resolve) => reader.readEntries(resolve));
      if (!batch.length) break;
      for (const child of batch) await walkEntry(child, files);
    }
  }

  document.getElementById("rank-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.target;
    const body = new FormData(form);
    body.append("confirm_replace", "0");
    let response = await fetch("/recruit/jd/rank", { method: "POST", body });
    if (response.status === 409) {
      if (!window.confirm("Replace the current job description and scores?")) return;
      body.set("confirm_replace", "1");
      response = await fetch("/recruit/jd/rank", { method: "POST", body });
    }
    const payload = await response.json();
    if (!response.ok) {
      rankStatus.textContent = payload.detail || payload.message || "Ranking failed.";
      return;
    }
    window.location.reload();
  });

  const loadReplies = document.getElementById("load-replies");
  if (loadReplies) {
    loadReplies.addEventListener("click", async () => {
      const profileId = document.getElementById("draft-profile").value;
      const response = await fetch("/recruit/jd/replies?profile_id=" + encodeURIComponent(profileId));
      const payload = await response.json();
      const list = document.getElementById("reply-list");
      if (!response.ok) {
        list.textContent = payload.detail || "Could not read mail.";
        return;
      }
      const messages = payload.messages || [];
      list.textContent = messages.length
        ? messages.map((item) => item.subject || "(no subject)").join(" · ")
        : "No recent mail from this address.";
      if (messages[0]) document.getElementById("reply-context").value = messages[0].subject || "";
    });
  }
})();
