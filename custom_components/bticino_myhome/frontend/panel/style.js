export const PANEL_STYLE = `
      <style>
        :host {
          display: block;
          min-height: 100%;
          background: var(--primary-background-color);
          color: var(--primary-text-color);
          font-family: var(--paper-font-body1_-_font-family, "Segoe UI", sans-serif);
        }
        .wrap {
          max-width: 1080px;
          margin: 18px auto 30px;
          padding: 14px;
        }
        .brand {
          display: flex;
          align-items: center;
          gap: 12px;
          margin-bottom: 12px;
          padding: 8px 0;
        }
        .brand-logo {
          width: 110px;
          height: 32px;
          object-fit: contain;
          display: block;
        }
        .brand-title {
          font-size: 1.1rem;
          font-weight: 600;
          margin: 0;
          line-height: 1.2;
        }
        .panel {
          border: 1px solid var(--divider-color);
          background: var(--card-background-color);
          padding: 12px;
          margin-bottom: 12px;
        }
        .panel.result {
          min-height: 190px;
        }
        .panel.config-panel {
          min-height: 190px;
        }
        .panel h3 {
          margin: 0 0 10px;
          font-size: 1rem;
        }
        details {
          border: 1px solid var(--divider-color);
          padding: 10px;
        }
        summary {
          cursor: pointer;
          font-weight: 600;
          user-select: none;
        }
        details[open] summary {
          margin-bottom: 10px;
        }
        .subpanel {
          border: 1px solid var(--divider-color);
          padding: 10px;
          margin-top: 10px;
        }
        .subpanel h4 {
          margin: 0 0 8px;
          font-size: 0.92rem;
          text-transform: uppercase;
          letter-spacing: 0.03em;
        }
        form {
          margin: 0;
        }
        .grid {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 10px;
          margin-bottom: 10px;
        }
        .checks {
          display: grid;
          grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
          gap: 8px;
          margin-bottom: 10px;
        }
        label {
          display: flex;
          flex-direction: column;
          gap: 5px;
          font-size: 0.9rem;
        }
        .checks label,
        .inline-check {
          flex-direction: row;
          align-items: center;
          gap: 8px;
        }
        .inline-flags {
          display: flex;
          flex-wrap: wrap;
          gap: 8px;
        }
        .detail-list {
          display: flex;
          flex-wrap: wrap;
          gap: 6px;
        }
        .detail-chip {
          border: 1px solid var(--divider-color);
          padding: 1px 4px;
          font-size: 0.78rem;
          background: var(--card-background-color);
        }
        select,
        input[type="number"],
        input[type="text"] {
          border: 1px solid var(--divider-color);
          padding: 7px;
          font: inherit;
          background: var(--card-background-color);
          color: var(--primary-text-color);
          min-width: 0;
        }
        .actions {
          display: flex;
          gap: 8px;
          flex-wrap: wrap;
          margin-top: 8px;
        }
        .row-between {
          display: flex;
          justify-content: space-between;
          align-items: center;
          gap: 8px;
        }
        button {
          border: 1px solid var(--divider-color);
          background: var(--card-background-color);
          color: var(--primary-text-color);
          padding: 8px 10px;
          font: inherit;
          cursor: pointer;
        }
        button[type="submit"] {
          border-color: var(--primary-color);
          color: var(--primary-color);
        }
        button.danger {
          border-color: #cc6666;
          color: #a33;
        }
        button[disabled] {
          opacity: 0.6;
          cursor: not-allowed;
        }
        .subtle {
          color: var(--secondary-text-color);
          font-size: 0.86rem;
          margin: 6px 0;
        }
        .error {
          border: 1px solid #cf6d6d;
          background: #f9ecec;
          color: #7a1e1e;
          padding: 10px;
          margin-bottom: 10px;
        }
        .notice {
          border: 1px solid #8bb78b;
          background: #ecf8ec;
          color: #245a24;
          padding: 10px;
          margin-bottom: 10px;
        }
        table {
          width: 100%;
          border-collapse: collapse;
          margin-top: 8px;
        }
        th,
        td {
          border-bottom: 1px solid var(--divider-color);
          text-align: left;
          padding: 7px 6px;
          vertical-align: top;
          font-size: 0.88rem;
        }
        th {
          font-size: 0.82rem;
          color: var(--secondary-text-color);
          text-transform: uppercase;
        }
        .row-actions {
          display: flex;
          gap: 6px;
          flex-wrap: wrap;
          align-items: center;
        }
        button.import-btn {
          border-color: var(--primary-color, #03a9f4);
          color: var(--primary-color, #03a9f4);
        }
        .import-modal-backdrop {
          position: fixed;
          inset: 0;
          background: rgba(0, 0, 0, 0.45);
          z-index: 200;
          display: flex;
          align-items: center;
          justify-content: center;
        }
        .import-modal {
          background: var(--card-background-color, #fff);
          color: var(--primary-text-color, #212121);
          border: 1px solid var(--divider-color, #e0e0e0);
          padding: 22px 24px;
          min-width: 320px;
          max-width: 480px;
          width: 90%;
          box-shadow: 0 4px 24px rgba(0,0,0,0.18);
        }
      </style>
`;
