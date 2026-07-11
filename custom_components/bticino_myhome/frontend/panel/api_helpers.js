export function createApiErrorMessage(panel, err, defaultMsg) {
  return err?.body?.message || err?.message || defaultMsg;
}

export function clearApiErrors(panel) {
  panel._error = "";
  panel._notice = "";
}

export function setApiError(panel, msg) {
  panel._error = msg;
}

export function setApiNotice(panel, msg) {
  panel._notice = msg;
}
