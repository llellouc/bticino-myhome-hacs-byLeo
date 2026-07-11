import { renderDeviceDetails } from "./helpers.js";
import { renderDiscoveryTableRows } from "./render_discovery_table.js";
export { renderImportModal } from "./modals/import_modal.js";

export function renderGatewayOptions(panel) {
  if (panel._gateways.length === 0) {
    return '<option value="">No gateway available</option>';
  }

  return panel._gateways
    .map((gateway) => {
      const selected = gateway.mac === panel._state.gateway ? "selected" : "";
      return `<option value="${panel._esc(gateway.mac)}" ${selected}>${panel._esc(gateway.name)} (${panel._esc(gateway.host)})</option>`;
    })
    .join("");
}

export function renderConfigDevices(panel) {
  const devices = panel._configDevices || {};
  const hasExistingConfig = Object.values(devices).some((items) => Array.isArray(items) && items.length > 0);
  if (panel._loadingConfig && !hasExistingConfig) {
    return '<div class="subtle">Loading configuration...</div>';
  }
  const platforms = ["light", "cover", "climate", "sensor"];
  let total = 0;

  const blocks = platforms
    .map((platform) => {
      const items = devices[platform] || [];
      total += items.length;
      const rows = items
        .map((item) => {
          const address = item.where || item.zone || "-";
          const canImport = platform === "sensor" && ["power", "power_energy", "energy", "water"].includes(item.class);
          const importBtn = canImport
            ? `<button type="button" class="import-btn"
                   data-import-key="${panel._esc(item.key)}"
                   data-import-name="${panel._esc(item.name || item.key)}"
                   data-import-where="${panel._esc(address)}"
                   data-import-class="${panel._esc(item.class)}"
                   data-import-scale="${panel._esc(item.unit_scale || "base")}">Import</button>`
            : "";
          return `
              <tr>
                <td><code>${panel._esc(item.key)}</code></td>
                <td>${panel._esc(item.name || "-")}</td>
                <td><code>${panel._esc(address)}</code></td>
                <td>${renderDeviceDetails(item, platform, panel._esc.bind(panel))}</td>
                <td class="row-actions">
                  ${importBtn}
                  <button type="button" class="danger" data-delete-platform="${platform}" data-delete-key="${panel._esc(item.key)}">Remove</button>
                </td>
              </tr>
            `;
        })
        .join("");

      return `
          <section class="subpanel">
            <h4>${platform} (${items.length})</h4>
            <table>
              <thead>
                <tr><th>Key</th><th>Name</th><th>Address</th><th>Details</th><th></th></tr>
              </thead>
              <tbody>
                ${rows || '<tr><td colspan="5" class="subtle">No devices</td></tr>'}
              </tbody>
            </table>
          </section>
        `;
    })
    .join("");

  return `
      ${panel._loadingConfig ? '<div class="subtle">Refreshing configuration...</div>' : ""}
      <div class="subtle">Configured devices: <strong>${total}</strong></div>
      ${blocks}
    `;
}

export function renderDiscoveryCandidates(panel) {
  const header = `
      <div class="row-between">
        <h3>Discovered devices (automatic discovery)</h3>
        <div class="actions">
          <button id="show_activation_discovery" type="button" ${panel._loadingActivation ? "disabled" : ""}>${panel._loadingActivation ? "Refreshing..." : "Refresh results"}</button>
          <button id="show_activation_discovery_clear" type="button" ${panel._loadingActivation ? "disabled" : ""}>Clear list</button>
        </div>
      </div>
    `;

  if (!panel._result) {
    return `
        <section class="panel result">
          ${header}
          <p class="subtle">No results available yet. Trigger devices physically, then press "Refresh results".</p>
        </section>
      `;
  }

  const entries = panel._candidateEntries();
  const selected = entries.filter((entry) => entry.selected).length;

  const summary = `
      <p class="subtle">
        Gateway: <code>${panel._esc(panel._result.gateway)}</code> |
        new: lights <strong>${panel._result.new_light?.length || 0}</strong>,
        cover <strong>${panel._result.new_cover?.length || 0}</strong>,
        climate <strong>${panel._result.new_climate?.length || 0}</strong>,
        power <strong>${panel._result.new_power?.length || 0}</strong>
      </p>
    `;

  if (entries.length === 0) {
    return `
        <section class="panel result">
          ${header}
          ${summary}
          <p class="subtle">No new devices to import. Detected endpoints are either already configured or not yet activated.</p>
        </section>
      `;
  }

  const rows = renderDiscoveryTableRows(entries, panel);

  return `
      <section class="panel result">
        ${header}
        ${summary}
        <div class="subtle">Selezionati per import: <strong>${selected}</strong> / ${entries.length}</div>
        <table>
          <thead>
            <tr><th></th><th>Type</th><th>Address</th><th>Key</th><th>Name</th><th>Options</th></tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="actions">
          <button id="import_selected_candidates" type="button" ${panel._savingConfig ? "disabled" : ""}>${panel._savingConfig ? "Importing..." : "Import selected into configuration"}</button>
        </div>
      </section>
    `;
}
