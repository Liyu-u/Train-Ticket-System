-- 04_financial_view.sql
-- 说明：创建视图 `v_daily_financial_report`，用于日度财务统计（按日期和车次分组）。
-- 视图字段说明：
--  - sale_date: 订单日期（基于 create_time 的日期部分）
--  - train_id: 车次编号
--  - total_orders: 当日该车次的订单总数（包含所有状态）
--  - paid_orders: 当日已支付订单数（status = 1）
--  - refunded_orders: 当日已退票订单数（status = 2）
--  - total_sales: 当日已支付订单的总金额（SUM(price) WHERE status=1）
--  - refund_amount: 当日已退票订单的总金额（SUM(price) WHERE status=2）
--  - net_revenue: 净收入 = total_sales - refund_amount

DROP VIEW IF EXISTS v_daily_financial_report;

CREATE VIEW v_daily_financial_report AS
SELECT
    DATE(o.create_time) AS sale_date,
    o.train_id,
    COUNT(*) AS total_orders,
    SUM(CASE WHEN o.status = 1 THEN 1 ELSE 0 END) AS paid_orders,
    SUM(CASE WHEN o.status = 2 THEN 1 ELSE 0 END) AS refunded_orders,
    COALESCE(SUM(CASE WHEN o.status = 1 THEN o.price ELSE 0 END), 0) AS total_sales,
    COALESCE(SUM(CASE WHEN o.status = 2 THEN o.price ELSE 0 END), 0) AS refund_amount,
    COALESCE(SUM(CASE WHEN o.status = 1 THEN o.price ELSE 0 END), 0)
      - COALESCE(SUM(CASE WHEN o.status = 2 THEN o.price ELSE 0 END), 0) AS net_revenue
FROM orders o
WHERE o.create_time IS NOT NULL
GROUP BY DATE(o.create_time), o.train_id;

-- 兼容性：此视图使用标准 SQL 聚合与 CASE 表达式，兼容 MySQL 8.0。
-- 使用示例：
-- SELECT * FROM v_daily_financial_report WHERE sale_date = CURDATE();
