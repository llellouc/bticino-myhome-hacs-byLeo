import {
  buildCandidateImportBody,
  buildManualDeviceBody,
} from "./helpers.js";

export async function ensurePassiveDiscoveryEnabled(panel) {
  if (!panel._hass || !panel._state.gateway) {
    return;
  }
  try {
    const response = await panel._hass.callApi("POST", "bticino_myhome/discovery_by_activation", {
      gateway: panel._state.gateway,
      enabled: true,
    });
    panel._state.discovery_by_activation = !!response.enabled;
    const selectedGateway = panel._gatewayByMac(response.gateway);
    if (selectedGateway) {
      selectedGateway.discovery_by_activation = !!response.enabled;
    }
  } catch (_err) {
    // Best-effort: actual error surfaced by refresh call.
  }
}

export async function loadGateways(panel) {
  if (!panel._hass) {
    return;
  }
  panel._loadingGateways = true;
  panel._error = "";
  panel._render();
  try {
    const response = await panel._hass.callApi("GET", "bticino_myhome/gateways");
    panel._gateways = response.gateways || [];
    if (!panel._state.gateway && panel._gateways.length > 0) {
      panel._syncGatewayState(panel._gateways[0].mac);
    } else if (panel._state.gateway) {
      panel._syncGatewayState(panel._state.gateway);
    }
    await panel._ensurePassiveDiscoveryEnabled();
    await panel._loadConfiguration();
    await panel._showActivationResults(false, false);
  } catch (err) {
    panel._error = `Error loading gateways: ${err?.body?.message || err?.message || "unknown"}`;
  } finally {
    panel._loadingGateways = false;
    panel._render();
  }
}

export async function loadConfiguration(panel) {
  if (!panel._hass || !panel._state.gateway) {
    return;
  }
  panel._loadingConfig = true;
  panel._render();
  try {
    const encodedGateway = encodeURIComponent(panel._state.gateway);
    const response = await panel._hass.callApi(
      "GET",
      `bticino_myhome/configuration?gateway=${encodedGateway}`,
    );
    panel._configDevices = response.devices || {};
  } catch (err) {
    panel._error = err?.body?.message || err?.message || "Error loading configuration.";
  } finally {
    panel._loadingConfig = false;
    panel._render();
  }
}

export async function showActivationResults(panel, clear, renderStart = true) {
  if (!panel._hass || !panel._state.gateway) {
    return;
  }
  panel._loadingActivation = true;
  if (renderStart) {
    panel._error = "";
    panel._notice = "";
    panel._render();
  }

  try {
    panel._result = await panel._hass.callApi("POST", "bticino_myhome/activation_discovery", {
      gateway: panel._state.gateway,
      clear,
    });
    panel._state.discovery_by_activation = !!panel._result.enabled;
    panel._refreshCandidateDrafts();
    if (clear) {
      panel._notice = "Automatic discovery list cleared.";
    }
  } catch (err) {
    panel._error = err?.body?.message || err?.message || "Unable to read automatic discovery results.";
  } finally {
    panel._loadingActivation = false;
    panel._render();
  }
}

export async function importSelectedCandidates(panel) {
  if (!panel._hass || !panel._state.gateway) {
    return;
  }

  const selected = panel._candidateEntries().filter((entry) => entry.selected);
  if (selected.length === 0) {
    panel._notice = "No selected devices to import.";
    panel._error = "";
    panel._render();
    return;
  }

  panel._savingConfig = true;
  panel._error = "";
  panel._notice = "";
  panel._render();

  let imported = 0;
  const failures = [];

  for (const candidate of selected) {
    const body = buildCandidateImportBody(panel._state.gateway, candidate);

    try {
      await panel._hass.callApi("POST", "bticino_myhome/configuration/device", body);
      imported += 1;
    } catch (err) {
      failures.push(`${candidate.platform}:${candidate.address} -> ${err?.body?.message || err?.message || "error"}`);
    }
  }

  await panel._loadConfiguration();
  await panel._showActivationResults(false, false);

  if (imported > 0) {
    panel._notice = `Import completed: ${imported} devices.`;
  }
  if (failures.length > 0) {
    panel._error = `Partial import. Errors: ${failures.join(" | ")}`;
  }

  panel._savingConfig = false;
  panel._render();
}

export async function saveManualDevice(panel, event) {
  if (event && typeof event.preventDefault === "function") {
    event.preventDefault();
  }
  if (!panel._hass || !panel._state.gateway) {
    return;
  }

  const previousScrollY = typeof window !== "undefined" ? window.scrollY : 0;

  panel._readManualState();
  panel._savingConfig = true;
  panel._error = "";
  panel._notice = "";
  panel._render();

  try {
    const body = buildManualDeviceBody(panel._state.gateway, panel._state);

    const response = await panel._hass.callApi("POST", "bticino_myhome/configuration/device", body);
    panel._configDevices = response.devices || panel._configDevices;
    panel._notice = `Device saved (${response.platform}:${response.key}).`;
    panel._state.manual_key = "";
    panel._state.manual_name = "";
    panel._state.manual_address = "";
  } catch (err) {
    panel._error = err?.body?.message || err?.message || "Device save failed.";
  } finally {
    panel._savingConfig = false;
    panel._render();
    if (typeof window !== "undefined") {
      window.scrollTo({ top: previousScrollY, behavior: "auto" });
    }
  }
}

export async function deleteDevice(panel, platform, key) {
  if (!panel._hass || !panel._state.gateway || !platform || !key) {
    return;
  }

  const previousScrollY = typeof window !== "undefined" ? window.scrollY : 0;

  panel._savingConfig = true;
  panel._error = "";
  panel._notice = "";
  panel._render();

  try {
    const response = await panel._hass.callApi("POST", "bticino_myhome/configuration/device_delete", {
      gateway: panel._state.gateway,
      platform,
      key,
    });
    panel._configDevices = response.devices || panel._configDevices;
    panel._notice = `Device removed (${platform}:${key}).`;
  } catch (err) {
    panel._error = err?.body?.message || err?.message || "Device removal failed.";
  } finally {
    panel._savingConfig = false;
    panel._render();
    if (typeof window !== "undefined") {
      window.scrollTo({ top: previousScrollY, behavior: "auto" });
    }
  }
}

export async function runImportForModal(panel) {
  if (!panel._importModal || panel._importInProgress) return;
  if (!panel._hass || !panel._state.gateway) return;

  panel._importInProgress = true;
  panel._importModal = { ...panel._importModal, result: null, error: null };
  panel._render();

  try {
    const response = await panel._hass.callApi("POST", "bticino_myhome/energy/import_daily", {
      gateway: panel._state.gateway,
      sensor_key: panel._importModal.key,
      overwrite: !!panel._importModal.overwrite,
      months_back: panel._importModal.monthsBack,
      query_delay_ms: 200,
    });
    const importedCount = (response.imported || []).reduce((acc, item) => acc + (item.rows || 0), 0);
    panel._importModal = {
      ...panel._importModal,
      result: `Import terminé : ${importedCount} point(s) importé(s).`,
      error: (response.errors || []).length > 0 ? response.errors.join(" | ") : null,
    };
  } catch (err) {
    panel._importModal = {
      ...panel._importModal,
      error: err?.body?.message || err?.message || "Import échoué.",
    };
  } finally {
    panel._importInProgress = false;
    panel._render();
  }
}
