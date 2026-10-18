const list = document.querySelector("#list");
const status = document.querySelector("#status");

function extract() {
  const emailPattern = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi;
  const blocks = document.body.innerText.split(/\n{2,}/).slice(0, 40);
  const profiles = [];
  blocks.forEach((block, index) => {
    const email = (block.match(emailPattern) || [])[0] || "";
    const lines = block.split("\n").map((line) => line.trim()).filter(Boolean);
    if (!email && lines.length < 2) return;
    profiles.push({
      portal_id: `tab-${index}-${email || lines[0] || index}`,
      name: lines[0] || "",
      email,
      snippet: lines.slice(0, 6).join(" ").slice(0, 400),
      skills: "",
    });
  });
  return profiles;
}

document.querySelector("#capture").addEventListener("click", async () => {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  const [result] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func: extract });
  list.innerHTML = "";
  (result.result || []).forEach((profile, index) => {
    const label = document.createElement("label");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = true;
    box.dataset.index = String(index);
    label.append(box, document.createTextNode(` ${profile.name || profile.email || "Profile"}`));
    list.append(label);
  });
  window.__profiles = result.result || [];
  status.textContent = `${window.__profiles.length} visible blocks.`;
});

document.querySelector("#send").addEventListener("click", async () => {
  const origin = document.querySelector("#origin").value.replace(/\/$/, "");
  const portal = document.querySelector("#portal").value || "browser";
  const chosen = [];
  list.querySelectorAll("input:checked").forEach((box) => {
    const profile = (window.__profiles || [])[Number(box.dataset.index)];
    if (profile) chosen.push({ ...profile, portal });
  });
  const response = await fetch(`${origin}/recruit/jd/portals/import`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ portal, profiles: chosen }),
  });
  status.textContent = response.ok ? "Sent to Talent Scout." : "Sign in to Talent Scout in this browser, then try again.";
});
