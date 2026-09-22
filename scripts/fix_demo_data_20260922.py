"""演示数据存量修正（2026-09-22，对应 docs/新版前端说明.md 第五节 1、2）。

1. 3 条非法状态 PLACED 订单按到货情况改为后端认可的状态，事件名对齐 ORDERED。
2. 批量种子订单（PO-270xxx）的 order_date 摊入近 150 天，使 30 天趋势窗口有数据。

注意：PyMySQL 的 ``with conn`` 退出时只 close 不 commit（服务器随之回滚），
必须显式 conn.commit()；且验证读取必须放在 commit 之后——
事务内自读永远能看到自己的修改，掩盖"从未提交"的问题（本脚本首版踩过此坑）。

用法（backend 目录下）：PYTHONPATH=. python ../scripts/fix_demo_data_20260922.py
"""

import pymysql

from app.core.config import get_settings


def main() -> None:
    s = get_settings()
    conn = pymysql.connect(
        host=s.mysql_host,
        port=s.mysql_port,
        user=s.mysql_user,
        password=s.mysql_password,
        database=s.mysql_database,
        charset="utf8mb4",
    )
    with conn:
        with conn.cursor() as cur:
            # ---- 写入阶段 ----
            # 1) PLACED → 按到货情况映射（收满 COMPLETED / 部分 PARTIAL / 在途 ORDERED）
            cur.execute(
                "UPDATE purchase_orders SET status='COMPLETED' "
                "WHERE po_no='PO-26001' AND status='PLACED'"
            )
            r1 = cur.rowcount
            cur.execute(
                "UPDATE purchase_orders SET status='PARTIAL' "
                "WHERE po_no='PO-26002' AND status='PLACED'"
            )
            r2 = cur.rowcount
            cur.execute(
                "UPDATE purchase_orders SET status='ORDERED' "
                "WHERE po_no='PO-26003' AND status='PLACED'"
            )
            r3 = cur.rowcount
            cur.execute(
                "UPDATE purchase_order_events "
                "SET event_type='ORDERED', to_status='ORDERED', event_note='订单已正式下单' "
                "WHERE event_type='PLACED' OR to_status='PLACED'"
            )
            r4 = cur.rowcount
            # 2) 批量种子单 order_date 摊入近 150 天（含 30 天趋势窗口）。
            #    以 (id - 186) 为偏移：186 是 PO-270 批次的最小 id，
            #    保证 0–149 天均匀分布（镜像种子 index%150 的意图），
            #    约 30 条落入 30 天窗口，而不是挤在 36–149 天前。
            cur.execute(
                "UPDATE purchase_orders "
                "SET order_date = DATE_SUB(CURDATE(), INTERVAL ((id - 186) % 150) DAY) "
                "WHERE po_no LIKE 'PO-270%'"
            )
            r5 = cur.rowcount
        # 显式提交——不依赖 with conn（PyMySQL 1.4.6 的 __exit__ 不 commit）
        conn.commit()
        print(f"committed: placed={r1 + r2 + r3} events={r4} order_date={r5}")

        # ---- 验证阶段：必须在 commit 之后 ----
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM purchase_orders WHERE status='PLACED'")
            placed_left = cur.fetchone()[0]
            cur.execute(
                "SELECT po_no, status FROM purchase_orders "
                "WHERE po_no IN ('PO-26001','PO-26002','PO-26003') ORDER BY po_no"
            )
            orders = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*), MIN(order_date), MAX(order_date) "
                "FROM purchase_orders WHERE po_no LIKE 'PO-270%'"
            )
            spread = cur.fetchone()
            cur.execute(
                "SELECT COUNT(DISTINCT order_date) FROM purchase_orders "
                "WHERE order_date >= DATE_SUB(CURDATE(), INTERVAL 29 DAY) "
                "AND order_date <= CURDATE()"
            )
            window_days = cur.fetchone()[0]
            cur.execute(
                "SELECT COUNT(*) FROM purchase_orders "
                "WHERE po_no LIKE 'PO-270%' "
                "AND order_date <> DATE_SUB(CURDATE(), INTERVAL ((id - 186) % 150) DAY)"
            )
            mismatch = cur.fetchone()[0]

    print(f"VERIFY after commit — PLACED left: {placed_left} (expect 0)")
    print("VERIFY orders:", orders)
    print(
        f"VERIFY PO-270 range: {spread[1]} ~ {spread[2]} "
        f"(total {spread[0]}), formula mismatch: {mismatch}"
    )
    print(f"VERIFY distinct order_date in last-30-day window: {window_days}")
    assert placed_left == 0, "PLACED 未清零——提交可能失败"
    assert mismatch == 0, f"仍有 {mismatch} 行 order_date 不符合摊开公式"
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
