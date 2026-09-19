import { FormEvent, useEffect, useRef, useState } from "react";
import { deleteAIConversation, getAIConversationMessages, getAIConversations, streamAIChat, uploadModuleFile } from "../services/api";
import type { AIQueryTrace } from "../services/api";
import AIQueryTracePanel from "./AIQueryTracePanel";

type MessageTrace = {
  label: string;
  kind: "tool" | "json";
  status: "done" | "running";
  detail: string;
};

type ChatMessage = {
  id: number;
  role: "assistant" | "user";
  content: string;
  attachments?: string[];
  sources?: string[];
  trace?: MessageTrace[];
  queryTrace?: AIQueryTrace;
};

type ChatThread = {
  id: string;
  conversationId?: number;
  title: string;
  preview: string;
  time: string;
  messages: ChatMessage[];
};

type PanelPosition = {
  x: number;
  y: number;
};

type PendingAttachment = {
  id: string;
  name: string;
  size: string;
  fileId: number;
};

const quickPrompts = ["查看本周逾期到货", "推荐可采购的供应商", "分析库存预警"];

function renderMarkdown(source: string) {
  const escaped = source.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\"/g, "&quot;");
  const html = escaped
    .replace(/```([\s\S]*?)```/g, (_, code: string) => `<pre><code>${code.trim()}</code></pre>`)
    .replace(/^### (.+)$/gm, "<h4>$1</h4>")
    .replace(/^## (.+)$/gm, "<h3>$1</h3>")
    .replace(/^# (.+)$/gm, "<h2>$1</h2>")
    .replace(/^[-*] (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>[\s\S]*?<\/li>)(?=\s*(?:<li>|$))/g, "$1")
    .replace(/(?:<li>.*<\/li>\s*)+/g, (items: string) => `<ul>${items}</ul>`)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\n/g, "<br />");
  return { __html: html };
}

function buildMessageTrace(citations?: unknown[] | null, content = "", running = false): MessageTrace[] {
  const trace: MessageTrace[] = [];
  if (running) trace.push({ label: "AI 输出", kind: "tool", status: "running", detail: "正在生成回答…" });
  const fence = String.fromCharCode(96);
  const jsonPattern = new RegExp(fence + "{3}(?:json)?\\s*([\\s\\S]*?)" + fence + "{3}", "gi");
  for (const match of content.matchAll(jsonPattern)) {
    const raw = match[1].trim();
    let detail = raw;
    try { detail = JSON.stringify(JSON.parse(raw), null, 2); } catch { /* 保留原始 JSON 文本。 */ }
    trace.push({ label: "JSON 状态", kind: "json", status: "done", detail });
  }
  const sources = citationSourceLabels(citations);
  if (sources.length) {
    trace.push({ label: "工具调用", kind: "tool", status: "done", detail: sources.join("\n") });
  }
  if (!trace.length && !running) {
    trace.push({ label: "回答状态", kind: "tool", status: "done", detail: "回答已生成，未返回额外工具或 JSON 状态。" });
  }
  return trace;
}

const initialThreads: ChatThread[] = [
  {
    id: "procurement",
    title: "化运助手",
    preview: "从采购申请到订单执行，随时帮你梳理业务…",
    time: "刚刚",
    messages: [
      {
        id: 1,
        role: "assistant",
        content: "你好，我是化运助手。你可以让我帮你查采购、库存、到货和供应商信息。",
      },
    ],
  },
];

function formatThreadTime(value?: string | null) {
  if (!value) return "刚刚";
  return value.replace("T", " ").slice(5, 16);
}

function formatFileSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function citationFileNames(citations?: unknown[] | null) {
  return (citations || []).flatMap((citation) => {
    if (!citation || typeof citation !== "object") return [];
    const fileName = (citation as { file_name?: unknown }).file_name;
    return typeof fileName === "string" && fileName ? [fileName] : [];
  });
}

function citationSourceLabels(citations?: unknown[] | null) {
  return (citations || []).flatMap((citation) => {
    if (!citation || typeof citation !== "object") return [];
    const source = (citation as { source?: unknown }).source;
    const type = (citation as { type?: unknown }).type;
    if ((type === "dashboard_overview" || type === "business_context") && typeof source === "string") return [source];
    if (type === "text2sql" && typeof source === "string") return ["Text2SQL · " + source];
    return [];
  });
}

function queryTraceFromCitations(citations?: unknown[] | null): AIQueryTrace | undefined {
  for (const citation of citations || []) {
    if (!citation || typeof citation !== "object") continue;
    const trace = (citation as { query_trace?: unknown }).query_trace;
    if (trace && typeof trace === "object" && "query" in trace && "slots" in trace && "rows" in trace) return trace as AIQueryTrace;
  }
  return undefined;
}

export default function AIFloatingAssistant({ token }: { token: string }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [position, setPosition] = useState<PanelPosition | null>(null);
  const [dragging, setDragging] = useState(false);
  const [activeThreadId, setActiveThreadId] = useState("procurement");
  const [threads, setThreads] = useState<ChatThread[]>(initialThreads);
  const [threadSearch, setThreadSearch] = useState("");
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [sending, setSending] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [streamingMessageId, setStreamingMessageId] = useState<number | null>(null);
  const [loadingThreadId, setLoadingThreadId] = useState<string | null>(null);
  const [deleteCandidate, setDeleteCandidate] = useState<ChatThread | null>(null);
  const [deletingThreadId, setDeletingThreadId] = useState<string | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const messagesRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dragOffset = useRef({ x: 0, y: 0 });

  const activeThread = threads.find((thread) => thread.id === activeThreadId) || threads[0];
  const messages = activeThread?.messages || [];
  const visibleThreads = threads.filter((thread) => `${thread.title} ${thread.preview}`.toLowerCase().includes(threadSearch.trim().toLowerCase()));

  useEffect(() => {
    messagesRef.current?.scrollTo({ top: messagesRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    let cancelled = false;
    void getAIConversations(token).then((result) => {
      if (cancelled || !result.items.length) return;
      const loadedThreads = result.items.map((item) => ({
        id: `conversation-${item.id}`,
        conversationId: item.id,
        title: item.title || "未命名会话",
        preview: "点击加载历史消息",
        time: formatThreadTime(item.last_message_at || item.updated_at),
        messages: [],
      }));
      setThreads(loadedThreads);
      const firstId = `conversation-${result.items[0].id}`;
      setActiveThreadId(firstId);
      setLoadingThreadId(firstId);
      void getAIConversationMessages(token, result.items[0].id).then((messagesResult) => {
        if (cancelled) return;
        setThreads((current) => current.map((item) => item.id === firstId ? {
          ...item,
          preview: messagesResult.items.at(-1)?.content || item.preview,
          messages: messagesResult.items.map((message) => ({ id: message.id, role: message.role === "user" ? "user" : "assistant", content: message.content, attachments: citationFileNames(message.citations), sources: citationSourceLabels(message.citations), trace: buildMessageTrace(message.citations, message.content), queryTrace: queryTraceFromCitations(message.citations) })),
        } : item));
      }).catch(() => undefined).finally(() => setLoadingThreadId(null));
    }).catch(() => {
      // 历史接口不可用时保留当前新建会话，发送时仍会展示后端错误。
    });
    return () => { cancelled = true; };
  }, [token]);

  useEffect(() => {
    if (open) createThread();
  }, [open]);
  useEffect(() => {
    if (!dragging) return;

    function movePanel(event: PointerEvent) {
      const panel = panelRef.current;
      if (!panel) return;
      const margin = 14;
      const width = panel.offsetWidth;
      const height = panel.offsetHeight;
      const x = Math.min(Math.max(margin, event.clientX - dragOffset.current.x), window.innerWidth - width - margin);
      const y = Math.min(Math.max(margin, event.clientY - dragOffset.current.y), window.innerHeight - height - margin);
      setPosition({ x, y });
    }

    function stopDragging() {
      setDragging(false);
    }

    window.addEventListener("pointermove", movePanel);
    window.addEventListener("pointerup", stopDragging);
    return () => {
      window.removeEventListener("pointermove", movePanel);
      window.removeEventListener("pointerup", stopDragging);
    };
  }, [dragging]);

  function startDragging(event: React.PointerEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).closest("button")) return;
    const panel = panelRef.current;
    if (!panel) return;
    const rect = panel.getBoundingClientRect();
    dragOffset.current = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    setPosition({ x: rect.left, y: rect.top });
    setDragging(true);
  }

  function createThread() {
    const id = `thread-${Date.now()}`;
    setThreads((current) => [
      { id, title: "新建对话", preview: "开始一段新的业务分析", time: "刚刚", messages: [] },
      ...current,
    ]);
    setActiveThreadId(id);
    setDraft("");
    setAttachments([]);
  }

  async function selectThread(id: string) {
    setActiveThreadId(id);
    setDraft("");
    setAttachments([]);
    const thread = threads.find((item) => item.id === id);
    if (!thread?.conversationId || thread.messages.length) return;
    setLoadingThreadId(id);
    try {
      const result = await getAIConversationMessages(token, thread.conversationId);
      setThreads((current) => current.map((item) => item.id === id ? {
        ...item,
        preview: result.items.at(-1)?.content || item.preview,
        messages: result.items.map((message) => ({ id: message.id, role: message.role === "user" ? "user" : "assistant", content: message.content, attachments: citationFileNames(message.citations), sources: citationSourceLabels(message.citations), trace: buildMessageTrace(message.citations, message.content), queryTrace: queryTraceFromCitations(message.citations) })),
      } : item));
    } catch {
      setThreads((current) => current.map((item) => item.id === id ? { ...item, preview: "历史消息加载失败，请重试" } : item));
    } finally {
      setLoadingThreadId(null);
    }
  }

  async function handleFiles(event: React.ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []);
    if (!files.length) return;
    event.target.value = "";
    try {
      const uploaded = await Promise.all(files.map(async (file) => {
        const result = await uploadModuleFile<{ id: number }>(token, file, "AI_ATTACHMENT", "PRIVATE");
        return { id: `${file.name}-${file.lastModified}`, name: file.name, size: formatFileSize(file.size), fileId: result.id };
      }));
      setAttachments((current) => [...current, ...uploaded]);
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : "附件上传失败";
      setDraft((current) => `${current}${current ? "\n" : ""}附件上传失败：${message}`);
    }
  }

  async function sendMessage(event?: FormEvent, preset?: string) {
    event?.preventDefault();
    const content = (preset ?? draft).trim();
    if ((!content && !attachments.length) || sending) return;
    const selectedAttachments = [...attachments];
    const history = activeThread?.messages || [];
    const userMessage: ChatMessage = {
      id: Date.now(),
      role: "user",
      content: content || "请分析我上传的附件",
      attachments: selectedAttachments.map((item) => item.name),
    };
    setThreads((current) => current.map((thread) => thread.id === activeThreadId
      ? { ...thread, title: thread.title === "新建对话" ? userMessage.content.slice(0, 16) : thread.title, preview: userMessage.content, time: "刚刚", messages: [...thread.messages, userMessage] }
      : thread));
    setDraft("");
    setAttachments([]);
    setSending(true);
    setThinking(true);
    const assistantId = Date.now() + 1;
    try {
      setStreamingMessageId(assistantId);
      setThreads((current) => current.map((thread) => thread.id === activeThreadId ? { ...thread, messages: [...thread.messages, { id: assistantId, role: "assistant", content: "", trace: buildMessageTrace(null, "", true) }] } : thread));
      await streamAIChat(token, [...history, userMessage].map(({ role, content: messageContent }) => ({ role, content: messageContent })), selectedAttachments.map((item) => item.name), selectedAttachments.map((item) => item.fileId), (event) => {
        if (event.type === "delta") setThinking(false);
        if (event.type === "delta") setThreads((current) => current.map((thread) => thread.id === activeThreadId ? { ...thread, preview: `${thread.preview}${event.content}`, messages: thread.messages.map((message) => message.id === assistantId ? { ...message, content: `${message.content}${event.content}` } : message) } : thread));
        if (event.type === "done") setThinking(false);
        if (event.type === "done") setThreads((current) => current.map((thread) => thread.id === activeThreadId ? { ...thread, conversationId: event.conversation_id, time: "刚刚", messages: thread.messages.map((message) => message.id === assistantId ? { ...message, sources: citationSourceLabels(event.citations), trace: buildMessageTrace(event.citations, message.content), queryTrace: event.query_trace || queryTraceFromCitations(event.citations) } : message) } : thread));
        if (event.type === "error") throw new Error(event.message);
      });
    } catch (reason) {
      const assistantMessage: ChatMessage = { id: Date.now() + 1, role: "assistant", content: `AI 暂时无法回答：${reason instanceof Error ? reason.message : "服务暂时不可用，请稍后重试"}` };
      setThreads((current) => current.map((thread) => {
        if (thread.id !== activeThreadId) return thread;
        const hasPlaceholder = thread.messages.some((message) => message.id === assistantId);
        return {
          ...thread,
          preview: assistantMessage.content,
          time: "刚刚",
          messages: hasPlaceholder
            ? thread.messages.map((message) => message.id === assistantId ? { ...message, content: assistantMessage.content } : message)
            : [...thread.messages, assistantMessage],
        };
      }));
    } finally {
      setSending(false);
      setThinking(false);
      setStreamingMessageId(null);
    }
  }

  function removeThread(event: React.MouseEvent, thread: ChatThread) {
    event.stopPropagation();
    setDeleteCandidate(thread);
  }

  async function confirmRemoveThread() {
    const thread = deleteCandidate;
    if (!thread || deletingThreadId) return;
    setDeletingThreadId(thread.id);
    try {
      if (thread.conversationId) await deleteAIConversation(token, thread.conversationId);
      const remaining = threads.filter((item) => item.id !== thread.id);
      const nextThreads = remaining.length ? remaining : initialThreads;
      setThreads(nextThreads);
      if (activeThreadId === thread.id) setActiveThreadId(nextThreads[0].id);
      setDeleteCandidate(null);
    } catch (reason) {
      setDraft(reason instanceof Error ? reason.message : "删除会话失败，请稍后重试");
    } finally {
      setDeletingThreadId(null);
    }
  }

  const panelStyle = position
    ? { left: `${position.x}px`, top: `${position.y}px`, right: "auto", bottom: "auto" }
    : undefined;

  return (
    <div className="ai-assistant-layer">
      {open && (
        <section ref={panelRef} className={`ai-assistant-panel ${dragging ? "is-dragging" : ""}`} style={panelStyle} role="dialog" aria-label="化运助手">
          <aside className="ai-assistant-history">
            <div className="ai-history-brand"><span className="ai-history-brand-mark">✦</span><strong>化运助手</strong></div>
            <div className="ai-history-toolbar">
              <label className="ai-history-search"><span aria-hidden="true">⌕</span><input value={threadSearch} onChange={(event) => setThreadSearch(event.target.value)} aria-label="搜索历史会话" placeholder="搜索会话" /></label>
              <button type="button" aria-label="新建会话" title="新建会话" onClick={createThread}>＋</button>
            </div>
            <div className="ai-history-label">最近对话</div>
            <nav className="ai-thread-list" aria-label="历史会话">
              {visibleThreads.map((thread) => (
                <div key={thread.id} className={`ai-thread-item ${thread.id === activeThreadId ? "active" : ""}`} role="button" tabIndex={0} onClick={() => void selectThread(thread.id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") void selectThread(thread.id); }}>
                  <span className="ai-thread-avatar">✦</span>
                  <span className="ai-thread-copy"><strong>{thread.title}</strong><small>{thread.preview}</small></span>
                  <time>{thread.time}</time>
                  <button type="button" className="ai-thread-delete" aria-label={`删除会话 ${thread.title}`} title="删除会话" onClick={(event) => void removeThread(event, thread)}>×</button>
                </div>
              ))}
            </nav>
            <div className="ai-history-footer"><span className="ai-history-status-dot" />会话已保存到当前账号</div>
          </aside>

          <div className="ai-assistant-main">
            <div className="ai-assistant-header" onPointerDown={startDragging}>
              <div className="ai-assistant-heading">
                <span className="ai-assistant-mark" aria-hidden="true">✦</span>
                <span><strong>{activeThread?.title || "化运助手"}</strong><small><i />业务数据助手 · 可拖动</small></span>
              </div>
              <div className="ai-assistant-header-actions">
                <button type="button" aria-label="收起 AI 聊天窗" onClick={() => setOpen(false)}>−</button>
                <button type="button" aria-label="关闭 AI 聊天窗" onClick={() => setOpen(false)}>×</button>
              </div>
            </div>

            <div ref={messagesRef} className="ai-assistant-messages">
              <div className="ai-assistant-context">当前工作区 · {activeThread?.title || "业务分析"}</div>
              {loadingThreadId === activeThreadId && <div className="ai-empty-thread"><span>…</span><strong>正在加载历史消息</strong><small>正在从数据库恢复本次会话。</small></div>}
              {messages.length === 0 && loadingThreadId !== activeThreadId && <div className="ai-empty-thread"><span>✦</span><strong>开始一段新的分析</strong><small>从下方输入问题，或选择一个快捷问题。</small></div>}
              {messages.map((message) => (
                <div key={message.id} className={`ai-message-row ${message.role}`}>
                  {message.role === "assistant" && <span className="ai-message-avatar" aria-hidden="true">✦</span>}
                  <div className="ai-message-stack"><div className="ai-message-bubble">{message.id === streamingMessageId && sending && thinking && !message.content ? <span className="ai-thinking-state" role="status" aria-live="polite"><span className="ai-thinking-dots" aria-hidden="true"><i /><i /><i /></span><span>AI 正在思考…</span></span> : <span dangerouslySetInnerHTML={renderMarkdown(message.content)} />}{message.id === streamingMessageId && sending && !thinking && <span className="ai-stream-cursor" aria-label="正在输出" />}</div>{message.queryTrace ? <AIQueryTracePanel trace={message.queryTrace} /> : null}{message.attachments?.length ? <div className="ai-message-attachments">{message.attachments.map((name) => <span key={name}>▧ {name}</span>)}</div> : null}{message.sources?.length ? <div className="ai-message-sources">来源：{message.sources.join("、")}</div> : null}{message.trace?.length ? <details className="ai-message-trace"><summary><span>◇</span>执行状态 <em>{message.trace.length} 项</em></summary><div className="ai-trace-list">{message.trace.map((trace) => <div key={`${message.id}-${trace.label}`} className="ai-trace-item"><div><b>{trace.kind === "json" ? "{}" : "✦"}</b><strong>{trace.label}</strong><small className={trace.status}>{trace.status === "running" ? "进行中" : "已完成"}</small></div><pre>{trace.detail}</pre></div>)}</div></details> : null}</div>
                </div>
              ))}
              {messages.length <= 1 && <div className="ai-quick-prompts"><span>可以试试</span><div>{quickPrompts.map((prompt) => <button key={prompt} type="button" disabled={sending} onClick={() => void sendMessage(undefined, prompt)}>{prompt}</button>)}</div></div>}
            </div>

            <form className="ai-assistant-composer" onSubmit={sendMessage}>
              {attachments.length > 0 && <div className="ai-pending-attachments">{attachments.map((item) => <span key={item.id} title={item.name}>▧ {item.name}<small>{item.size}</small><button type="button" aria-label={`移除附件 ${item.name}`} onClick={() => setAttachments((current) => current.filter((file) => file.id !== item.id))}>×</button></span>)}</div>}
              <div className="ai-composer-input-row">
                <textarea value={draft} onChange={(event) => setDraft(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) sendMessage(event); }} placeholder="输入消息，Ctrl / ⌘ + Enter 发送…" aria-label="输入 AI 问题" rows={2} />
                <button className="ai-send-button" type="submit" aria-label="发送消息" disabled={sending || (!draft.trim() && !attachments.length)}>{sending ? (thinking ? "思考中…" : "回答中…") : "发送"}</button>
              </div>
              <div className="ai-composer-toolbar">
                <div className="ai-composer-tools">
                  <button type="button" aria-label="添加表情" title="表情" onClick={() => setDraft((current) => `${current}${current ? " " : ""}🙂`)}>☺</button>
                  <button type="button" aria-label="上传附件" title="上传附件" onClick={() => fileInputRef.current?.click()}>⌕</button>
                  <button type="button" aria-label="上传文件" title="上传文件" onClick={() => fileInputRef.current?.click()}>▧</button>
                  <input ref={fileInputRef} type="file" multiple hidden onChange={handleFiles} />
                </div>
              </div>
            </form>
            <p className="ai-assistant-footnote">AI 建议仅供参考，正式业务操作仍需确认。</p>
          </div>
        </section>
      )}

      {deleteCandidate && (
        <div className="ai-delete-modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget && !deletingThreadId) setDeleteCandidate(null); }}>
          <div className="ai-delete-modal" role="dialog" aria-modal="true" aria-labelledby="ai-delete-title">
            <div className="ai-delete-modal-icon">!</div>
            <div className="ai-delete-modal-copy">
              <span>删除历史对话</span>
              <h3 id="ai-delete-title">确定删除“{deleteCandidate.title}”吗？</h3>
              <p>删除后，这段对话和其中的消息将无法恢复。</p>
            </div>
            <div className="ai-delete-modal-actions">
              <button type="button" className="ai-delete-cancel" disabled={Boolean(deletingThreadId)} onClick={() => setDeleteCandidate(null)}>取消</button>
              <button type="button" className="ai-delete-confirm" disabled={Boolean(deletingThreadId)} onClick={() => void confirmRemoveThread()}>{deletingThreadId ? "删除中…" : "确定删除"}</button>
            </div>
          </div>
        </div>
      )}

      <button type="button" className={`ai-assistant-fab ${open ? "is-open" : ""}`} aria-label={open ? "收起 AI 助手" : "打开 AI 助手"} aria-expanded={open} onClick={() => setOpen((current) => !current)}>
        <span className="ai-fab-orbit" aria-hidden="true" />
        <span className="ai-fab-symbol" aria-hidden="true">✦</span>
        <span className="ai-fab-label">AI</span>
      </button>
    </div>
  );
}
