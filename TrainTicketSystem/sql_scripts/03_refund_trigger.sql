-- 03_refund_trigger.sql
-- 说明：当 `orders` 表中的订单状态更新为“已退票”时，自动恢复对应 `seat_status` 的位图。
-- 适配说明：
--  - 触发器会尝试通过订单中的 `train_id`、`carriage` 与 `seat` 字段定位 `seat_status` 中的记录（字段名为 carriage_no、seat_no）。
--  - 使用位运算清除已退票区间：`seat_bitmap = seat_bitmap & (~ seat_mask)`。
--  - 该脚本对 MySQL 8.0 兼容，并包含幂等性判断（若触发器已存在则先删除）。

-- 以单语句形式创建触发器，方便通过 PyMySQL 直接执行（无需 DELIMITER/BEGIN...END）
DROP TRIGGER IF EXISTS trg_orders_after_update_refund;
CREATE TRIGGER trg_orders_after_update_refund
AFTER UPDATE ON orders
FOR EACH ROW
    -- 当订单状态从非退款变为退款（数值状态 2）时，清理 seat_status 中对应座位的位图
    UPDATE seat_status
    SET seat_bitmap = seat_bitmap & (~ NEW.buy_mask)
    WHERE seat_id = NEW.seat_id
      AND NEW.status = 2
      AND (OLD.status IS NULL OR OLD.status != 2);

-- 使用说明：将此脚本在目标数据库上执行一次以创建触发器。
-- 注意事项：确保 `orders` 与 `seat_status` 的字段名与脚本中的匹配，如存在差异请做相应替换。
