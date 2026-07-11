export function bindManualFormEvents(panel) {
  const manualForm = panel.querySelector("#manual_device_form");
  if (manualForm) {
    manualForm.addEventListener("submit", panel._saveManualDevice.bind(panel));
  }

  const manualSaveButton = panel.querySelector("#manual_save_device");
  if (manualSaveButton) {
    manualSaveButton.addEventListener("click", (event) => panel._saveManualDevice(event));
  }

  const manualPlatform = panel.querySelector("#manual_platform");
  if (manualPlatform) {
    manualPlatform.addEventListener("change", () => {
      panel._readManualState();
      panel._render();
    });
  }

  const manualSensorClass = panel.querySelector("#manual_sensor_class");
  if (manualSensorClass) {
    manualSensorClass.addEventListener("change", () => {
      panel._readManualState();
      const context = panel._sensorUnitContext(panel._state.manual_sensor_class);
      if (!context.supportsScale) {
        panel._state.manual_sensor_unit_scale = "base";
      }
      panel._render();
    });
  }

  const manualSection = panel.querySelector("#manual_section");
  if (manualSection) {
    manualSection.addEventListener("toggle", () => {
      panel._state.manual_section_open = !!manualSection.open;
    });
  }
}
