export function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function sensorUnitContext(sensorClass) {
  const cls = String(sensorClass || "").toLowerCase();
  if (cls === "water") {
    return {
      supportsScale: true,
      baseLabel: "Base (L et L/h)",
      kiloLabel: "Kilo (m3 et m3/h)",
      help: "water: debit/volume en L/Lh ou m3/m3h.",
    };
  }
  if (cls === "power") {
    return {
      supportsScale: true,
      baseLabel: "Base (W)",
      kiloLabel: "Kilo (kW)",
      help: "power: puissance instantanee uniquement, en W ou kW.",
    };
  }
  if (cls === "power_energy") {
    return {
      supportsScale: true,
      baseLabel: "Base (W + Wh)",
      kiloLabel: "Kilo (kW + kWh)",
      help: "power/energy: puissance instantanee (W) + energie cumulee (Wh ou kWh).",
    };
  }
  if (cls === "energy") {
    return {
      supportsScale: true,
      baseLabel: "Base (Wh)",
      kiloLabel: "Kilo (kWh)",
      help: "energy: energie cumulee en Wh ou kWh.",
    };
  }
  return {
    supportsScale: false,
    baseLabel: "Base",
    kiloLabel: "Kilo",
    help: `${cls || "sensor"}: unite fixe, echelle non applicable.`,
  };
}

export function defaultCandidate(platform, address) {
  if (platform === "light") {
    return {
      id: `${platform}:${address}`,
      selected: true,
      platform,
      address,
      key: `discovered_light_${address}`,
      name: `Light ${address}`,
      dimmable: false,
    };
  }
  if (platform === "cover") {
    return {
      id: `${platform}:${address}`,
      selected: true,
      platform,
      address,
      key: `discovered_cover_${address}`,
      name: `Cover ${address}`,
    };
  }
  if (platform === "climate") {
    return {
      id: `${platform}:${address}`,
      selected: true,
      platform,
      address,
      key: `discovered_climate_${address}`,
      name: `Climate ${address}`,
      heat: true,
      cool: true,
      fan: true,
      standalone: true,
    };
  }
  return {
    id: `${platform}:${address}`,
    selected: true,
    platform,
    address,
    key: `discovered_power_${address}`,
    name: `Power+Energy ${address}`,
    class: "power_energy",
    unit_scale: "base",
  };
}

export function sortedCandidateEntries(candidateDrafts) {
  return Object.values(candidateDrafts).sort((a, b) => a.id.localeCompare(b.id));
}

export function buildCandidateImportBody(gateway, candidate) {
  const body = {
    gateway,
    platform: candidate.platform,
    key: candidate.key,
    name: candidate.name,
  };

  if (candidate.platform === "climate") {
    body.zone = candidate.address;
    body.heat = !!candidate.heat;
    body.cool = !!candidate.cool;
    body.fan = !!candidate.fan;
    body.standalone = !!candidate.standalone;
  } else {
    body.where = candidate.address;
  }

  if (candidate.platform === "light") {
    body.dimmable = !!candidate.dimmable;
  }
  if (candidate.platform === "sensor") {
    body.class = candidate.class || "power_energy";
    body.unit_scale = candidate.unit_scale || "base";
  }

  return body;
}

export function buildManualDeviceBody(gateway, state) {
  const platform = state.manual_platform;
  const body = {
    gateway,
    platform,
    key: state.manual_key,
    name: state.manual_name,
  };

  if (platform === "climate") {
    body.zone = state.manual_address;
    body.heat = state.manual_heat;
    body.cool = state.manual_cool;
    body.fan = state.manual_fan;
    body.standalone = state.manual_standalone;
  } else {
    body.where = state.manual_address;
  }

  if (platform === "light") {
    body.dimmable = state.manual_dimmable;
  }
  if (platform === "sensor") {
    body.class = state.manual_sensor_class;
    body.unit_scale = state.manual_sensor_unit_scale || "base";
  }

  return body;
}

export function renderDeviceDetails(item, platform, esc) {
  const details = [];

  if (platform === "light") {
    details.push(`dimmable=${item.dimmable ? "true" : "false"}`);
  }
  if (platform === "sensor" && item.class) {
    details.push(`class=${item.class}`);
    details.push(`unit_scale=${item.unit_scale || "base"}`);
  }
  if (platform === "climate") {
    details.push(`heat=${item.heat ? "true" : "false"}`);
    details.push(`cool=${item.cool ? "true" : "false"}`);
    details.push(`fan=${item.fan ? "true" : "false"}`);
    details.push(`standalone=${item.standalone ? "true" : "false"}`);
  }
  if (item.who !== undefined && item.who !== null && item.who !== "") {
    details.push(`who=${item.who}`);
  }
  if (item.interface !== undefined && item.interface !== null && item.interface !== "") {
    details.push(`interface=${item.interface}`);
  }
  if (item.manufacturer) {
    details.push(`manufacturer=${item.manufacturer}`);
  }
  if (item.model) {
    details.push(`model=${item.model}`);
  }

  if (details.length === 0) {
    return '<span class="subtle">-</span>';
  }

  return `
      <div class="detail-list">
        ${details.map((detail) => `<code class="detail-chip">${esc(detail)}</code>`).join("")}
      </div>
    `;
}
