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
        </section>

        <details className="ai-query-trace-json">
          <summary><span>{"{}"}</span><strong>查看返回 JSON</strong><em>rows + slots + sql</em></summary>
          <pre>{jsonValue(trace)}</pre>
        </details>

      </div>
    </details>
  );
}
