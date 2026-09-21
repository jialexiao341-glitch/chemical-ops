import { FormEvent, useState } from "react";

type DialogBase = {
  title: string;
  description?: string;
  confirmText?: string;
  onClose: () => void;
};

export function TextPromptDialog({ title, description, label, placeholder, required = false, confirmText = "确定", onClose, onSubmit }: DialogBase & { label: string; placeholder?: string; required?: boolean; onSubmit: (value: string) => Promise<void> | void }) {
  const [value, setValue] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (required && !value.trim()) { setError(`请填写${label}`); return; }
    try {
      setError("");
      setSaving(true);
      await onSubmit(value);
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败，请稍后重试");
    } finally {
      setSaving(false);
    }
  }

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onClose(); }}><form className="modal surface action-dialog" onSubmit={submit} role="dialog" aria-modal="true" aria-labelledby="prompt-dialog-title"><div className="section-heading"><div><h2 id="prompt-dialog-title">{title}</h2>{description && <p className="dialog-description">{description}</p>}</div><button type="button" className="icon-button" aria-label="关闭对话框" onClick={onClose} disabled={saving}>×</button></div><label className="dialog-field">{label}<input value={value} onChange={(event) => setValue(event.target.value)} placeholder={placeholder} autoFocus /></label>{error && <div className="inline-error">{error}</div>}<div className="modal-actions"><button type="button" className="outline-button" onClick={onClose} disabled={saving}>取消</button><button className="primary-button" disabled={saving}>{saving ? "处理中…" : confirmText}</button></div></form></div>;
}

export function ConfirmDialog({ title, description, confirmText = "确定", onClose, onConfirm }: DialogBase & { onConfirm: () => Promise<void> | void }) {
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function confirm() {
    try {
      setError("");
      setSaving(true);
      await onConfirm();
      onClose();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "操作失败，请稍后重试");
    } finally {
      setSaving(false);
    }
  }

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !saving) onClose(); }}><div className="modal surface action-dialog" role="dialog" aria-modal="true" aria-labelledby="confirm-dialog-title"><div className="section-heading"><div><h2 id="confirm-dialog-title">{title}</h2>{description && <p className="dialog-description">{description}</p>}</div><button type="button" className="icon-button" aria-label="关闭对话框" onClick={onClose} disabled={saving}>×</button></div>{error && <div className="inline-error">{error}</div>}<div className="modal-actions"><button type="button" className="outline-button" onClick={onClose} disabled={saving}>取消</button><button type="button" className="primary-button" onClick={() => void confirm()} disabled={saving}>{saving ? "处理中…" : confirmText}</button></div></div></div>;
}
