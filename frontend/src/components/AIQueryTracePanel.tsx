import type { AIQueryColumn, AIQueryTrace } from "../services/api";

function formatCell(value: unknown, column: AIQueryColumn) {
  if (value === null || value === undefined || value === "") return "—";
  if (column.format === "amount") {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(numeric);
  }
  return String(value);
}

function jsonValue(value: unknown) {
  return JSON.stringify(value, null, 2);
}

function BarChart({ trace }: { trace: AIQueryTrace }) {
  const visualization = trace.render.visualization;
  if (!visualization || visualization.type !== "bar" || !trace.rows.length) return null;
  const values = trace.rows.map((row) => Number(row[visualization.value])).filter((value) => Number.isFinite(value));
  const max = Math.max(...values, 1);
  return (
    <div className="ai-query-chart" aria-label={visualization.title}>
      <div className="ai-query-chart-title">{visualization.title}</div>
      {trace.rows.map((row, index) => {
        const value = Number(row[visualization.value]);
        if (!Number.isFinite(value)) return null;
        const label = String(row[visualization.category] ?? "—");
        return <div className="ai-query-chart-row" key={`${label}-${index}`}><span title={label}>{label}</span><div className="ai-query-chart-track"><i style={{ width: `${Math.max((value / max) * 100, 2)}%` }} /></div><b>{formatCell(value, trace.render.columns.find((column) => column.key === visualization.value) || { key: visualization.value, label: visualization.value, format: "text" })}</b></div>;
      })}
    </div>
  );
}

export default function AIQueryTracePanel({ trace }: { trace: AIQueryTrace }) {
  const columns = trace.render.columns.length ? trace.render.columns : trace.columns;
  return (
    <details className="ai-query-trace" open>
      <summary>
        <span className="ai-query-trace-mark">⌘</span>
        <span className="ai-query-trace-title">查询详情</span>
        <em>{trace.row_count} 条结果</em>
      </summary>
      <div className="ai-query-trace-body">
        <section className="ai-query-trace-section ai-query-trace-query">
          <div className="ai-query-trace-section-head"><span>01</span><strong>你的问题</strong></div>
          <p>{trace.query}</p>
          {trace.dataset_label ? <div className="ai-query-source-meta">数据源：{trace.dataset_label}{trace.permission ? ` · 权限：${trace.permission}` : ""}{trace.executed_at ? ` · ${new Date(trace.executed_at).toLocaleString("zh-CN")}` : ""}</div> : null}
          {trace.context?.continued ? <div className="ai-query-context-meta">↳ 继承上一轮条件：{Array.isArray(trace.context.inherited) ? trace.context.inherited.length : 0} 项 · 本轮修改：{Array.isArray(trace.context.changed) ? trace.context.changed.length : 0} 项</div> : null}
        </section>

        <section className="ai-query-trace-section">
          <div className="ai-query-trace-section-head"><span>02</span><strong>查询条件</strong><small>{trace.slots.filter((slot) => slot.status === "filled").length}/{trace.slots.length} 项</small></div>
          <div className="ai-query-slot-grid">
            {trace.slots.map((slot) => (
              <div className={"ai-query-slot " + (slot.status === "empty" ? "is-empty" : "")} key={slot.name}>
                <small>{slot.label}</small>
                <strong>{slot.display_value}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="ai-query-trace-section">
          <div className="ai-query-trace-section-head"><span>03</span><strong>查询模板</strong></div>
          <code className="ai-query-template">{trace.template}</code>
        </section>

        <details className="ai-query-trace-section ai-query-code">
          <summary><span>04</span><strong>查询语句</strong><em>只读</em></summary>
          <pre>{trace.sql}</pre>
        </details>

        <section className="ai-query-trace-section ai-query-result-section">
          <div className="ai-query-trace-section-head"><span>05</span><strong>{trace.render.title}</strong><small>{trace.truncated ? "仅展示部分" : String(trace.row_count) + " 条"}</small></div>
          {trace.rows.length ? (
            <div className="ai-query-result-table-wrap">
              <table className="ai-query-result-table" aria-label={trace.render.title}>
                <thead><tr>{columns.map((column) => <th scope="col" key={column.key}>{column.label}</th>)}</tr></thead>
                <tbody>{trace.rows.map((row, index) => <tr key={String(row.id || index)}>{columns.map((column) => <td key={column.key} className={column.format === "amount" ? "is-amount" : ""}>{formatCell(row[column.key], column)}</td>)}</tr>)}</tbody>
              </table>
            </div>
          ) : <div className="ai-query-empty">{trace.render.empty_text}</div>}
          <BarChart trace={trace} />
        </section>

        <details className="ai-query-trace-json">
          <summary><span>{"{}"}</span><strong>查看返回 JSON</strong><em>rows + slots + sql</em></summary>
          <pre>{jsonValue(trace)}</pre>
        </details>

      </div>
    </details>
  );
}
