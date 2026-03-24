/**
 * Vendor creation dialog manager.
 *
 * Opens a <dialog> for creating new vendors, handles address lookup
 * via fetch(), and populates #vendor-input on success.
 */
const VendorForm = (() => {
  // --- DOM references (resolved once) ---
  let dialog, title, error, displayName, addr1, addr2, city, state, zip, phone, candidates;
  let debounceTimer = null;
  let requestGen = 0;
  let vendorName = "";  // original typed name, sent as vendor_name for backend fallback

  function init() {
    dialog = document.getElementById("vendor-dialog");
    title = document.getElementById("vf-title");
    error = document.getElementById("vf-error");
    displayName = document.getElementById("vf-display-name");
    addr1 = document.getElementById("vf-addr1");
    addr2 = document.getElementById("vf-addr2");
    city = document.getElementById("vf-city");
    state = document.getElementById("vf-state");
    zip = document.getElementById("vf-zip");
    phone = document.getElementById("vf-phone");
    candidates = document.getElementById("vf-candidates");

    if (!dialog) return;

    // Close on backdrop click
    dialog.addEventListener("click", (e) => {
      if (e.target === dialog) close();
    });

    // Debounced address re-lookup on city/zip change
    city.addEventListener("input", () => debouncedLookup());
    zip.addEventListener("input", () => debouncedLookup());
  }

  function open(name) {
    vendorName = name;
    // Clear previous state
    title.textContent = name;
    displayName.value = name;
    error.style.display = "none";
    error.textContent = "";
    addr1.value = "";
    addr2.value = "";
    city.value = "";
    state.value = "";
    zip.value = "";
    phone.value = "";
    candidates.innerHTML = "";

    // Clear the vendor dropdown behind us
    document.getElementById("vendor-dropdown").innerHTML = "";

    dialog.showModal();
    lookupAddress();
  }

  function close() {
    ++requestGen;
    dialog.close();
    candidates.innerHTML = "";
    clearTimeout(debounceTimer);
  }

  function debouncedLookup() {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(lookupAddress, 500);
  }

  async function lookupAddress() {
    const gen = ++requestGen;
    const formData = new FormData();
    formData.append("vendor_name", vendorName);
    formData.append("display_name", displayName.value);
    formData.append("addr_city", city.value);
    formData.append("addr_zip", zip.value);

    try {
      const resp = await fetch("/vendors/lookup-address", {
        method: "POST",
        body: formData,
      });
      const data = await resp.json();
      if (gen !== requestGen) return;
      renderCandidates(data.candidates, data.message);
    } catch (err) {
      renderCandidates([], "Address lookup unavailable");
    }
  }

  function renderCandidates(items, message) {
    if (!items || items.length === 0) {
      candidates.innerHTML = message
        ? `<p class="error-msg" style="margin-top:0.25rem">${escapeHtml(message)}</p>`
        : "";
      return;
    }

    let html = `<div style="margin-top:0.25rem; border:1px solid #aaa; border-radius:4px; overflow:hidden">`;
    html += `<div style="padding:0.3rem 0.6rem; background:#f5f5f5; font-size:0.8rem; color:#555">`;
    html += `${items.length} result${items.length !== 1 ? "s" : ""} — select a match or edit the fields below manually</div>`;
    html += `<div style="max-height:9rem; overflow-y:auto">`;

    items.forEach((c, i) => {
      const dist = c.distance != null ? ` <span style="color:#888; font-size:0.85rem">(${c.distance.toFixed(1)} mi)</span>` : "";
      html += `<div class="candidate-item" data-index="${i}" onclick="VendorForm._selectCandidate(this, ${i})">`;
      html += `<strong>${escapeHtml(c.name)}</strong>${dist}`;
      html += `<br><small style="color:#555">${escapeHtml(c.formatted_address)}</small>`;
      html += `</div>`;
    });

    html += `</div></div>`;
    candidates.innerHTML = html;

    // Store candidate data for selection
    candidates._data = items;
  }

  function selectCandidate(el, index) {
    const c = candidates._data[index];
    if (!c) return;

    addr1.value = c.addr_line1 || "";
    // Parse "City, ST ZIP" from addr_line2 (US format; non-US leaves city/state/zip blank)
    const a2 = c.addr_line2 || "";
    const m = a2.match(/^(.*),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)$/);
    addr2.value = "";
    city.value = m ? m[1] : "";
    state.value = m ? m[2] : "";
    zip.value = m ? m[3] : "";
    phone.value = c.phone || "";
    candidates.innerHTML = "";
  }

  async function create() {
    const name = displayName.value.trim();
    if (!name) {
      showError("Display name is required.");
      return;
    }

    const formData = new FormData();
    formData.append("vendor_name", vendorName);
    formData.append("display_name", name);
    formData.append("addr_line1", addr1.value);
    formData.append("addr_line2", addr2.value);
    formData.append("addr_city", city.value);
    formData.append("addr_state", state.value);
    formData.append("addr_zip", zip.value);
    formData.append("addr_phone", phone.value);

    try {
      const resp = await fetch("/vendors/create", {
        method: "POST",
        body: formData,
      });
      const data = await resp.json();
      if (data.ok) {
        document.getElementById("vendor-input").value = data.display_name;
        close();
      } else {
        showError(data.error || "Failed to create vendor.");
      }
    } catch (err) {
      showError("Request failed — check your connection.");
    }
  }

  function showError(msg) {
    error.textContent = msg;
    error.style.display = "block";
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  // Initialize when DOM is ready
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  return { open, close, create, _selectCandidate: selectCandidate };
})();
