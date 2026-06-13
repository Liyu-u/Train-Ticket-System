-- ============================================================
-- 05_train_stops.sql : 列车停靠站表（动态路由核心）
-- ============================================================
-- 说明：
--   1. 本表将列车经停站信息结构化存储，stop_index 直接对应底层位图偏移量。
--   2. 位图模型：若某车次有 N 个停靠站，则有 N-1 个运行区间，
--      区间 k（从站 stop_index=k 到站 stop_index=k+1）对应位图 bit k。
--   3. 示例：G101 经停 北京南(0) → 济南西(1) → 南京南(2) → 上海虹桥(3)
--      区间 0（北京→济南）对应 bit 0, mask=1
--      区间 1（济南→南京）对应 bit 1, mask=2
--      区间 2（南京→上海）对应 bit 2, mask=4
--   4. 购票掩码公式 (start_idx→end_idx, 含起点不含终点区间):
--      buy_mask = ((1 << (end_idx - start_idx)) - 1) << start_idx
-- ============================================================

USE train_ticket;

-- -----------------------------------------------------------
-- 表 5：列车停靠站表 (train_stops)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS train_stops (
    id              INT AUTO_INCREMENT PRIMARY KEY   COMMENT '主键',
    train_id        VARCHAR(20) NOT NULL             COMMENT '关联车次编号',
    station_name    VARCHAR(100) NOT NULL            COMMENT '车站名称',
    stop_index      INT NOT NULL                     COMMENT '经停序号（从0开始），直接对应位图偏移量',
    arrival_time    DATETIME                         COMMENT '到站时间（首站可为NULL）',
    departure_time  DATETIME                         COMMENT '离站时间（末站可为NULL）',
    UNIQUE KEY uk_train_stop (train_id, stop_index),
    UNIQUE KEY uk_train_station (train_id, station_name),
    CONSTRAINT fk_stops_train
        FOREIGN KEY (train_id) REFERENCES train_info(train_id)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB COMMENT='列车停靠站表（动态路由核心 —— stop_index 对应位图偏移量）';

-- -----------------------------------------------------------
-- 预置 G101 停靠站数据（4 站 → 3 个运行区间）
-- -----------------------------------------------------------
INSERT IGNORE INTO train_stops (train_id, station_name, stop_index, arrival_time, departure_time) VALUES
    ('G101', '北京南',   0, NULL,                      '2026-07-01 08:00:00'),
    ('G101', '济南西',   1, '2026-07-01 10:30:00',    '2026-07-01 10:35:00'),
    ('G101', '南京南',   2, '2026-07-01 13:00:00',    '2026-07-01 13:05:00'),
    ('G101', '上海虹桥', 3, '2026-07-01 15:00:00',     NULL);
