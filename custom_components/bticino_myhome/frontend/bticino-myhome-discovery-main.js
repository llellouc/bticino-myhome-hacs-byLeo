import { PANEL_STYLE } from "./panel/style.js";
import {
  defaultCandidate,
  escapeHtml,
  sensorUnitContext,
  sortedCandidateEntries,
} from "./panel/helpers.js";
import {
  deleteDevice,
  ensurePassiveDiscoveryEnabled,
  importSelectedCandidates,
  loadConfiguration,
  loadGateways,
  runImportForModal,
  saveManualDevice,
  showActivationResults,
} from "./panel/api.js";
import { bindEvents } from "./panel/events.js";
import {
  renderConfigDevices,
  renderDiscoveryCandidates,
  renderGatewayOptions,
  renderImportModal,
} from "./panel/render.js";

class MyHOMEDiscoveryPanel extends HTMLElement {
  constructor() {
    super();
    this._hass = null;
    this._gateways = [];
    this._loadingGateways = false;
    this._loadingActivation = false;
    this._loadingConfig = false;
    this._savingConfig = false;
    this._result = null;
    this._configDevices = null;
    this._candidateDrafts = {};
    this._importModal = null;
    this._importInProgress = false;
    this._error = "";
    this._notice = "";
    this._state = {
      gateway: "",
      discovery_by_activation: true,
      manual_platform: "light",
      manual_key: "",
      manual_name: "",
      manual_address: "",
      manual_sensor_class: "power_energy",
      manual_sensor_unit_scale: "base",
      manual_dimmable: false,
      manual_heat: true,
      manual_cool: true,
      manual_fan: true,
      manual_standalone: true,
      manual_section_open: false,
    };
  }

  set hass(hass) {
    if (this.childElementCount > 0) {
      this._readGatewayState();
      this._readManualState();
    }
    this._hass = hass;
    if (!this._loadingGateways && this._gateways.length === 0) {
      this._loadGateways();
    }
    this._render();
  }

  _esc(value) {
    return escapeHtml(value);
  }

  _gatewayByMac(mac) {
    return this._gateways.find((gateway) => gateway.mac === mac);
  }

  _syncGatewayState(mac) {
    this._state.gateway = mac || "";
    this._state.discovery_by_activation = true;
    const selectedGateway = this._gatewayByMac(this._state.gateway);
    if (selectedGateway) {
      selectedGateway.discovery_by_activation = true;
    }
  }

  _readGatewayState() {
    const gateway = this.querySelector("#gateway");
    if (gateway) {
      this._state.gateway = gateway.value || this._state.gateway;
    }
  }

  _readManualState() {
    const root = this;
    const manualPlatform = root.querySelector("#manual_platform");
    if (manualPlatform) {
      this._state.manual_platform = manualPlatform.value || this._state.manual_platform;
    }
    const manualKey = root.querySelector("#manual_key");
    if (manualKey) {
      this._state.manual_key = manualKey.value || "";
    }
    const manualName = root.querySelector("#manual_name");
    if (manualName) {
      this._state.manual_name = manualName.value || "";
    }
    const manualAddress = root.querySelector("#manual_address");
    if (manualAddress) {
      this._state.manual_address = manualAddress.value || "";
    }
    const sensorClass = root.querySelector("#manual_sensor_class");
    if (sensorClass) {
      this._state.manual_sensor_class = sensorClass.value || "energy";
    }
    const sensorUnitScale = root.querySelector("#manual_sensor_unit_scale");
    if (sensorUnitScale) {
      this._state.manual_sensor_unit_scale = sensorUnitScale.value || "base";
    }
    const dimmable = root.querySelector("#manual_dimmable");
    if (dimmable) {
      this._state.manual_dimmable = !!dimmable.checked;
    }
    const heat = root.querySelector("#manual_heat");
    if (heat) {
      this._state.manual_heat = !!heat.checked;
    }
    const cool = root.querySelector("#manual_cool");
    if (cool) {
      this._state.manual_cool = !!cool.checked;
    }
    const fan = root.querySelector("#manual_fan");
    if (fan) {
      this._state.manual_fan = !!fan.checked;
    }
    const standalone = root.querySelector("#manual_standalone");
    if (standalone) {
      this._state.manual_standalone = !!standalone.checked;
    }
    const manualSection = root.querySelector("#manual_section");
    if (manualSection) {
      this._state.manual_section_open = !!manualSection.open;
    }
  }

  async _ensurePassiveDiscoveryEnabled() {
    await ensurePassiveDiscoveryEnabled(this);
  }

  async _loadGateways() {
    await loadGateways(this);
  }

  async _loadConfiguration() {
    await loadConfiguration(this);
  }

  _sensorUnitContext(sensorClass) {
    return sensorUnitContext(sensorClass);
  }

  _defaultCandidate(platform, address) {
    return defaultCandidate(platform, address);
  }

  _refreshCandidateDrafts() {
    const next = {};
    if (!this._result) {
      this._candidateDrafts = {};
      return;
    }

    const append = (platform, list) => {
      (list || []).forEach((address) => {
        const id = `${platform}:${address}`;
        next[id] = this._candidateDrafts[id] || this._defaultCandidate(platform, String(address));
      });
    };

    append("light", this._result.new_light);
    append("cover", this._result.new_cover);
    append("climate", this._result.new_climate);
    append("sensor", this._result.new_power);
    this._candidateDrafts = next;
  }

  _candidateEntries() {
    return sortedCandidateEntries(this._candidateDrafts);
  }

  async _showActivationResults(clear, renderStart = true) {
    await showActivationResults(this, clear, renderStart);
  }

  async _importSelectedCandidates() {
    await importSelectedCandidates(this);
  }

  async _saveManualDevice(event) {
    await saveManualDevice(this, event);
  }

  async _deleteDevice(platform, key) {
    await deleteDevice(this, platform, key);
  }

  _renderImportModal() {
    return renderImportModal(this);
  }

  async _runImportForModal() {
    await runImportForModal(this);
  }

  _bindEvents() {
    bindEvents(this);
  }

  _renderGatewayOptions() {
    return renderGatewayOptions(this);
  }

  _renderConfigDevices() {
    return renderConfigDevices(this);
  }

  _renderDiscoveryCandidates() {
    return renderDiscoveryCandidates(this);
  }

  _render() {
    const loadingGateways = this._loadingGateways ? "disabled" : "";
    const configDisabled = this._savingConfig || this._loadingGateways ? "disabled" : "";
    const manualPlatform = this._state.manual_platform;
    const addressLabel = manualPlatform === "climate" ? "Zone (Address)" : "Where (Address)";
    const manualSensorUnitContext = this._sensorUnitContext(this._state.manual_sensor_class);

    if (!manualSensorUnitContext.supportsScale && this._state.manual_sensor_unit_scale !== "base") {
      this._state.manual_sensor_unit_scale = "base";
    }

    const sensorClassField =
      manualPlatform === "sensor"
        ? `
              <label>Sensor class
                <select id="manual_sensor_class" ${configDisabled}>
                  <option value="power" ${this._state.manual_sensor_class === "power" ? "selected" : ""}>power</option>
                  <option value="power_energy" ${this._state.manual_sensor_class === "power_energy" ? "selected" : ""}>power/energy</option>
                  <option value="temperature" ${this._state.manual_sensor_class === "temperature" ? "selected" : ""}>temperature</option>
                  <option value="energy" ${this._state.manual_sensor_class === "energy" ? "selected" : ""}>energy</option>
                  <option value="water" ${this._state.manual_sensor_class === "water" ? "selected" : ""}>water</option>
                  <option value="illuminance" ${this._state.manual_sensor_class === "illuminance" ? "selected" : ""}>illuminance</option>
                </select>
              </label>
              ${manualSensorUnitContext.supportsScale ? `
                <label>Unit scale
                  <select id="manual_sensor_unit_scale" ${configDisabled}>
                    <option value="base" ${this._state.manual_sensor_unit_scale !== "kilo" ? "selected" : ""}>${this._esc(manualSensorUnitContext.baseLabel)}</option>
                    <option value="kilo" ${this._state.manual_sensor_unit_scale === "kilo" ? "selected" : ""}>${this._esc(manualSensorUnitContext.kiloLabel)}</option>
                  </select>
                </label>
              ` : ""}
              <span class="subtle">${this._esc(manualSensorUnitContext.help)}</span>
          `
        : "";

    const manualFlags =
      manualPlatform === "light"
        ? `
            <div class="checks">
              <label><input id="manual_dimmable" type="checkbox" ${this._state.manual_dimmable ? "checked" : ""} ${configDisabled} /> Dimmable</label>
            </div>
          `
        : manualPlatform === "climate"
          ? `
            <div class="checks">
              <label><input id="manual_heat" type="checkbox" ${this._state.manual_heat ? "checked" : ""} ${configDisabled} /> Heat</label>
              <label><input id="manual_cool" type="checkbox" ${this._state.manual_cool ? "checked" : ""} ${configDisabled} /> Cool</label>
              <label><input id="manual_fan" type="checkbox" ${this._state.manual_fan ? "checked" : ""} ${configDisabled} /> Fan</label>
              <label><input id="manual_standalone" type="checkbox" ${this._state.manual_standalone ? "checked" : ""} ${configDisabled} /> Standalone</label>
            </div>
          `
          : "";

    const errorBlock = this._error ? `<div class="error">${this._esc(this._error)}</div>` : "";
    const noticeBlock = this._notice ? `<div class="notice">${this._esc(this._notice)}</div>` : "";
    const logoUrl = "/api/bticino_myhome/panel/bticino-logo.svg";

    this.innerHTML = `
      ${PANEL_STYLE}

      <div class="wrap">
        <div class="brand">
          <img class="brand-logo" src="${logoUrl}" alt="bticino" />
          <h2 class="brand-title">bticino MyHome Unofficial Integration</h2>
        </div>

        <section class="panel">
          <div class="row-between">
            <h3>Automatic discovery</h3>
            <button id="reload_gateways" type="button" ${loadingGateways}>Reload gateways</button>
          </div>
          <div class="grid">
            <label>Gateway
              <select id="gateway" ${loadingGateways}>${this._renderGatewayOptions()}</select>
            </label>
          </div>
          <p class="subtle">Passive collection is always enabled. Devices are detected only when they are actually triggered (physically or by other apps).</p>
        </section>

        ${errorBlock}
        ${noticeBlock}
        ${this._renderDiscoveryCandidates()}

        <section class="panel config-panel">
          <div class="row-between">
            <h3>Device Configuration</h3>
            <button id="reload_config" type="button" ${this._loadingConfig ? "disabled" : ""}>Reload</button>
          </div>
          ${this._renderConfigDevices()}
        </section>

        <section class="panel">
          <details id="manual_section" ${this._state.manual_section_open ? "open" : ""}>
            <summary>Add device manually</summary>
            <form id="manual_device_form" action="javascript:void(0);">
              <div class="grid">
                <label>Platform
                  <select id="manual_platform" ${configDisabled}>
                    <option value="light" ${this._state.manual_platform === "light" ? "selected" : ""}>light</option>
                    <option value="cover" ${this._state.manual_platform === "cover" ? "selected" : ""}>cover</option>
                    <option value="climate" ${this._state.manual_platform === "climate" ? "selected" : ""}>climate</option>
                    <option value="sensor" ${this._state.manual_platform === "sensor" ? "selected" : ""}>sensor</option>
                  </select>
                </label>
                <label>Key (optional)
                  <input id="manual_key" type="text" value="${this._esc(this._state.manual_key)}" ${configDisabled} />
                </label>
                <label>Name
                  <input id="manual_name" type="text" value="${this._esc(this._state.manual_name)}" ${configDisabled} />
                </label>
                <label>${addressLabel}
                  <input id="manual_address" type="text" value="${this._esc(this._state.manual_address)}" ${configDisabled} />
                </label>
                ${sensorClassField}
              </div>
              <p class="subtle">Platform: <code>${manualPlatform}</code> | required field: <code>${manualPlatform === "climate" ? "zone" : "where"}</code></p>
              ${manualFlags}
              <div class="actions">
                <button id="manual_save_device" type="button" ${configDisabled}>${this._savingConfig ? "Saving..." : "Save device"}</button>
              </div>
            </form>
          </details>
        </section>
      </div>
      ${this._importModal ? this._renderImportModal() : ""}
    `;

    this._bindEvents();
  }
}

customElements.define("bticino-myhome-discovery-panel", MyHOMEDiscoveryPanel);
