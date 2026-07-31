import { bindManualFormEvents } from "./events_manual.js";

export function bindEvents(panel) {
  const gatewaySelect = panel.querySelector("#gateway");
  if (gatewaySelect) {
    gatewaySelect.addEventListener("change", async (event) => {
      panel._syncGatewayState(event.target.value || "");
      await panel._ensurePassiveDiscoveryEnabled();
      await panel._loadConfiguration();
      await panel._showActivationResults(false, false);
      panel._render();
    });
  }

  const reloadButton = panel.querySelector("#reload_gateways");
  if (reloadButton) {
    reloadButton.addEventListener("click", () => panel._loadGateways());
  }

  const refreshActivation = panel.querySelector("#show_activation_discovery");
  if (refreshActivation) {
    refreshActivation.addEventListener("click", () => panel._showActivationResults(false));
  }

  const clearActivation = panel.querySelector("#show_activation_discovery_clear");
  if (clearActivation) {
    clearActivation.addEventListener("click", () => panel._showActivationResults(true));
  }

  const importSelected = panel.querySelector("#import_selected_candidates");
  if (importSelected) {
    importSelected.addEventListener("click", () => panel._importSelectedCandidates());
  }

  bindManualFormEvents(panel);

  const reloadConfigButton = panel.querySelector("#reload_config");
  if (reloadConfigButton) {
    reloadConfigButton.addEventListener("click", () => panel._loadConfiguration());
  }

  panel.querySelectorAll("[data-delete-platform][data-delete-key]").forEach((button) => {
    button.addEventListener("click", () => {
      panel._deleteDevice(button.dataset.deletePlatform, button.dataset.deleteKey);
    });
  });

  panel.querySelectorAll("button[data-import-key]").forEach((btn) => {
    btn.addEventListener("click", () => {
      panel._importModal = {
        key: btn.dataset.importKey,
        name: btn.dataset.importName,
        where: btn.dataset.importWhere,
        sensorClass: btn.dataset.importClass,
        unitScale: btn.dataset.importScale,
        dontOverrideHourly: true,
        useHourlyDetail: true,
        monthsBack: 24,
        result: null,
        error: null,
      };
      panel._importInProgress = false;
      panel._render();
    });
  });

  const modalRunImport = panel.querySelector("#modal_run_import");
  if (modalRunImport) {
    modalRunImport.addEventListener("click", () => panel._runImportForModal());
  }

  const modalClose = panel.querySelector("#modal_close");
  if (modalClose) {
    modalClose.addEventListener("click", () => {
      if (!panel._importInProgress) {
        panel._importModal = null;
        panel._render();
      }
    });
  }

  const modalDontOverrideHourly = panel.querySelector("#modal_dont_override_hourly");
  if (modalDontOverrideHourly) {
    modalDontOverrideHourly.addEventListener("change", () => {
      if (panel._importModal) {
        panel._importModal = {
          ...panel._importModal,
          dontOverrideHourly: modalDontOverrideHourly.checked,
        };
      }
    });
  }

  const modalUseHourlyDetail = panel.querySelector("#modal_use_hourly_detail");
  if (modalUseHourlyDetail) {
    modalUseHourlyDetail.addEventListener("change", () => {
      if (panel._importModal) {
        panel._importModal = {
          ...panel._importModal,
          useHourlyDetail: modalUseHourlyDetail.checked,
        };
      }
    });
  }

  const modalMonthsBack = panel.querySelector("#modal_months_back");
  if (modalMonthsBack) {
    modalMonthsBack.addEventListener("change", () => {
      if (panel._importModal) {
        panel._importModal = { ...panel._importModal, monthsBack: parseInt(modalMonthsBack.value, 10) };
      }
    });
  }

  panel.querySelectorAll("[data-candidate-id][data-candidate-field]").forEach((element) => {
    const eventName = element.type === "text" ? "input" : "change";
    element.addEventListener(eventName, () => {
      const id = element.dataset.candidateId;
      const field = element.dataset.candidateField;
      const type = element.dataset.candidateType || "text";
      const candidate = panel._candidateDrafts[id];
      if (!candidate) {
        return;
      }
      if (type === "bool") {
        candidate[field] = !!element.checked;
      } else if (type === "text-bool") {
        candidate[field] = element.checked ? "kilo" : "base";
      } else {
        candidate[field] = element.value;
      }

      if (candidate.platform === "sensor" && field === "class") {
        const context = panel._sensorUnitContext(candidate.class);
        if (!context.supportsScale) {
          candidate.unit_scale = "base";
        }
        panel._render();
      }
    });
  });
}
