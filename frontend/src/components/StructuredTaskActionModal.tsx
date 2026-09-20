import { FormEvent, useState } from "react";

export type TaskActionKind = "update" | "comment" | "list-comments" | "detail";

type Props = {
  kind: TaskActionKind;
  onClose: () => void;
  onSubmit: (exceptionId: string, taskId: string, content: string) => Promise<void>;
};

export default function StructuredTaskActionModal({ kind, onClose, onSubmit }: Props) {
  const [exceptionId, setExceptionId] = useState("");
  const [taskId, setTaskId] = useState("");
  const [status, setStatus] = useState("PROCESSING");
  const [title, setTitle] = useState("");
  const [assigneeId, setAssigneeId] = useState("");
  const [dueAt, setDueAt] = useState("");
  const [completionNote, setCompletionNote] = useState("");
  const [comment, setComment] = useState("");
  const [attachmentFileId, setAttachmentFileId] = useState("");
  const [error, setError] = useState("");
  const isReadOnly = kind === "detail" || kind === "list-comments";
  const titleText = kind === "detail" ? "任务详情" : kind === "list-comments" ? "查看处理记录" : kind === "update" ? "更新异常任务" : "追加处理记录";
  const description = kind === "detail" ? "输入任务编号，查看负责人、状态和截止时间。" : kind === "list-comments" ? "输入任务编号，回看异常处置时间线。" : "使用字段化表单提交任务动作，不需要手写请求数据。";

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!/^\d+$/.test(exceptionId.trim()) || !/^\d+$/.test(taskId.trim())) { setError("异常 ID 和任务 ID 必须是数字"); return; }
    if (kind === "comment" && !comment.trim()) { setError("请填写处理记录"); return; }
    const data = kind === "update"
      ? { status, ...(title.trim() ? { title: title.trim() } : {}), assignee_id: assigneeId ? Number(assigneeId) : undefined, due_at: dueAt || null, completion_note: completionNote.trim() || null }
      : { content: comment.trim(), attachment_file_id: attachmentFileId ? Number(attachmentFileId) : undefined };
    try { setError(""); await onSubmit(exceptionId.trim(), taskId.trim(), isReadOnly ? "" : JSON.stringify(data)); } catch (reason) { setError(reason instanceof Error ? reason.message : "任务操作失败"); }
  }

  return <div className="modal-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}><form className="modal surface task-action-modal" onSubmit={submit}><div className="section-heading"><div><p className="eyebrow">任务流程 / 字段化操作</p><h2>{titleText}</h2><p className="modal-description">{description}</p></div><button type="button" className="icon-button" aria-label="关闭对话框" onClick={onClose}>×</button></div><div className="task-context"><span className="task-context-mark">↗</span><span><strong>关联异常任务</strong><small>先定位异常和任务，再执行当前动作。</small></span></div><div className="form-grid"><label>异常 ID<input inputMode="numeric" value={exceptionId} onChange={(event) => setExceptionId(event.target.value)} placeholder="例如 1024" autoFocus /></label><label>任务 ID<input inputMode="numeric" value={taskId} onChange={(event) => setTaskId(event.target.value)} placeholder="例如 205" /></label></div>{kind === "update" && <div className="form-grid task-structured-fields"><label>任务标题<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="可选，不修改可留空" /></label><label>负责人 ID<input inputMode="numeric" value={assigneeId} onChange={(event) => setAssigneeId(event.target.value)} placeholder="可选" /></label><label>任务状态<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="PROCESSING">处理中</option><option value="COMPLETED">已完成</option><option value="CANCELLED">已取消</option></select></label><label>截止时间<input type="datetime-local" value={dueAt} onChange={(event) => setDueAt(event.target.value)} /></label><label className="wide-field">完成说明<textarea value={completionNote} onChange={(event) => setCompletionNote(event.target.value)} placeholder="完成或取消时填写说明" /></label></div>}{kind === "comment" && <div className="form-grid"><label className="wide-field">处理记录<textarea value={comment} onChange={(event) => setComment(event.target.value)} placeholder="记录处理进展、沟通结果或下一步动作" /></label><label>附件文件 ID<input inputMode="numeric" value={attachmentFileId} onChange={(event) => setAttachmentFileId(event.target.value)} placeholder="可选" /></label></div>}{error && <div className="inline-error">{error}</div>}<div className="modal-actions"><button type="button" className="outline-button" onClick={onClose}>取消</button><button className="primary-button">{isReadOnly ? "查看" : "提交"}</button></div></form></div>;
}
