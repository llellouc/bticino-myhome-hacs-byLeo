export function renderImportModal(panel) {
  const m = panel._importModal;
  const dis = panel._importInProgress ? "disabled" : "";
  const months = [3, 6, 12, 18, 24];
  return `
      <div class="import-modal-backdrop">
        <div class="import-modal">
          <h3 style="margin:0 0 10px">Import historique &mdash; ${panel._esc(m.name)}</h3>
          <p class="subtle" style="margin:0 0 12px">
            Cl&eacute; : <code>${panel._esc(m.key)}</code> &bull; where=<code>${panel._esc(m.where)}</code> &bull; class=<code>${panel._esc(m.sensorClass)}</code>
          </p>
          <div class="grid" style="grid-template-columns:1fr 1fr;margin-bottom:12px">
            <label>Mois &agrave; importer
              <select id="modal_months_back" ${dis}>
                ${months.map((n) => `<option value="${n}" ${m.monthsBack === n ? "selected" : ""}>${n} mois</option>`).join("")}
              </select>
            </label>
          </div>
          <div class="checks" style="margin-bottom:14px">
            <label>
              <input id="modal_overwrite" type="checkbox" ${m.overwrite ? "checked" : ""} ${dis}/>
              Remplacer les jours d&eacute;j&agrave; import&eacute;s (upsert)
            </label>
          </div>
          ${m.result ? `<div class="notice">${panel._esc(m.result)}</div>` : ""}
          ${m.error ? `<div class="error">${panel._esc(m.error)}</div>` : ""}
          <div class="actions">
            <button id="modal_run_import" type="button" ${dis}>${panel._importInProgress ? "Import en cours\u2026" : "Lancer l\u2019import"}</button>
            <button id="modal_close" type="button" ${panel._importInProgress ? "disabled" : ""}>Fermer</button>
          </div>
        </div>
      </div>
    `;
}
