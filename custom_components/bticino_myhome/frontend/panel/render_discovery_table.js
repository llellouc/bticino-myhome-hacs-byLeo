export function renderDiscoveryTableRows(entries, panel) {
  return entries
    .map((entry) => {
      let options = "-";
      if (entry.platform === "light") {
        options = `
            <label class="inline-check"><input type="checkbox" data-candidate-id="${panel._esc(entry.id)}" data-candidate-field="dimmable" data-candidate-type="bool" ${entry.dimmable ? "checked" : ""}/> dimmable</label>
          `;
      }
      if (entry.platform === "sensor") {
        const unitContext = panel._sensorUnitContext(entry.class);
        options = `
            <select data-candidate-id="${panel._esc(entry.id)}" data-candidate-field="class">
              <option value="power" ${entry.class === "power" ? "selected" : ""}>power</option>
              <option value="power_energy" ${entry.class === "power_energy" ? "selected" : ""}>power/energy</option>
              <option value="energy" ${entry.class === "energy" ? "selected" : ""}>energy</option>
              <option value="water" ${entry.class === "water" ? "selected" : ""}>water</option>
              <option value="temperature" ${entry.class === "temperature" ? "selected" : ""}>temperature</option>
              <option value="illuminance" ${entry.class === "illuminance" ? "selected" : ""}>illuminance</option>
            </select>
            ${unitContext.supportsScale ? `
              <label>Unit scale
                <select data-candidate-id="${panel._esc(entry.id)}" data-candidate-field="unit_scale">
                  <option value="base" ${entry.unit_scale !== "kilo" ? "selected" : ""}>${panel._esc(unitContext.baseLabel)}</option>
                  <option value="kilo" ${entry.unit_scale === "kilo" ? "selected" : ""}>${panel._esc(unitContext.kiloLabel)}</option>
                </select>
              </label>
              <span class="subtle">${panel._esc(unitContext.help)}</span>
            ` : `<span class="subtle">${panel._esc(unitContext.help)}</span>`}
          `;
      }
      if (entry.platform === "climate") {
        options = `
            <div class="inline-flags">
              <label class="inline-check"><input type="checkbox" data-candidate-id="${panel._esc(entry.id)}" data-candidate-field="heat" data-candidate-type="bool" ${entry.heat ? "checked" : ""}/> heat</label>
              <label class="inline-check"><input type="checkbox" data-candidate-id="${panel._esc(entry.id)}" data-candidate-field="cool" data-candidate-type="bool" ${entry.cool ? "checked" : ""}/> cool</label>
              <label class="inline-check"><input type="checkbox" data-candidate-id="${panel._esc(entry.id)}" data-candidate-field="fan" data-candidate-type="bool" ${entry.fan ? "checked" : ""}/> fan</label>
              <label class="inline-check"><input type="checkbox" data-candidate-id="${panel._esc(entry.id)}" data-candidate-field="standalone" data-candidate-type="bool" ${entry.standalone ? "checked" : ""}/> standalone</label>
            </div>
          `;
      }

      return `
          <tr>
            <td>
              <input type="checkbox" data-candidate-id="${panel._esc(entry.id)}" data-candidate-field="selected" data-candidate-type="bool" ${entry.selected ? "checked" : ""}/>
            </td>
            <td><code>${panel._esc(entry.platform)}</code></td>
            <td><code>${panel._esc(entry.address)}</code></td>
            <td><input type="text" data-candidate-id="${panel._esc(entry.id)}" data-candidate-field="key" value="${panel._esc(entry.key)}"/></td>
            <td><input type="text" data-candidate-id="${panel._esc(entry.id)}" data-candidate-field="name" value="${panel._esc(entry.name)}"/></td>
            <td>${options}</td>
          </tr>
        `;
    })
    .join("");
}
