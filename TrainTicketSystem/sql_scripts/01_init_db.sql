-- ============================================================
-- 01_init_db.sql : 火车票售票系统 — 数据库建表脚本（权威 Schema）
-- ============================================================
-- 说明：
--   1. 本脚本是数据库结构的唯一权威定义，所有表的列名、类型以本文件为准。
--   2. db_setup.py 中的 CREATE TABLE IF NOT EXISTS 语句必须与本文件逐字一致。
--   3. 字符集：utf8mb4，引擎：InnoDB（支持事务与行级锁）。
-- ============================================================

-- 创建数据库（如不存在）
CREATE DATABASE IF NOT EXISTS train_ticket DEFAULT CHARSET utf8mb4;
USE train_ticket;

-- -----------------------------------------------------------
-- 表 1：列车车次信息表 (train_info)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS train_info (
    train_id       VARCHAR(20)   PRIMARY KEY   COMMENT '车次编号，如 G101',
    train_no       VARCHAR(20)                 COMMENT '车次号',
    departure      VARCHAR(100)  NOT NULL      COMMENT '始发站',
    arrival        VARCHAR(100)  NOT NULL      COMMENT '终点站',
    total_seats    INT           NOT NULL      COMMENT '总座位数',
    departure_time DATETIME      NOT NULL      COMMENT '发车时间',
    price          DECIMAL(10,2)               COMMENT '票价（元）'
) ENGINE=InnoDB COMMENT='列车基础信息表';

-- -----------------------------------------------------------
-- 表 2：座位区间状态表 (seat_status) — 核心位图模型
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS seat_status (
    seat_id       INT AUTO_INCREMENT PRIMARY KEY  COMMENT '座位全局唯一 ID',
    train_id      VARCHAR(20)  NOT NULL           COMMENT '所属车次编号',
    carriage_no   INT          NOT NULL           COMMENT '车厢号',
    seat_no       VARCHAR(10)  NOT NULL           COMMENT '座位号，如 01A',
    seat_bitmap   INT          DEFAULT 0          COMMENT '二进制区间占用状态：0=全空闲',
    default_mask  INT          DEFAULT 0          COMMENT '该座位的默认区间掩码',
    UNIQUE KEY uk_train_seat (train_id, carriage_no, seat_no)
) ENGINE=InnoDB COMMENT='高并发座位区间状态表（位图模型核心）';

-- -----------------------------------------------------------
-- 表 3：订单交易表 (orders)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    order_id     VARCHAR(64)   PRIMARY KEY            COMMENT '订单流水号',
    user_id      VARCHAR(64)   NOT NULL               COMMENT '购票用户 ID',
    train_id     VARCHAR(20)                          COMMENT '车次编号',
    seat_id      INT                                  COMMENT '关联 seat_status.seat_id',
    buy_mask     INT           DEFAULT 0              COMMENT '本次购买的区间掩码',
    price        DECIMAL(10,2) DEFAULT 0              COMMENT '订单金额',
    order_status VARCHAR(20)   DEFAULT 'PAID'         COMMENT '字符串状态：PAID / REFUNDED',
    status       INT           DEFAULT 1              COMMENT '数值状态：1=已支付, 2=已退票（触发器与视图使用此字段）',
    create_time  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP COMMENT '订单创建时间'
) ENGINE=InnoDB COMMENT='交易订单表';

-- -----------------------------------------------------------
-- 表 4：用户权限表 (users)
-- -----------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id     VARCHAR(50)  PRIMARY KEY             COMMENT '用户唯一 ID',
    username    VARCHAR(50)  NOT NULL UNIQUE         COMMENT '登录账号',
    password    VARCHAR(256) NOT NULL                COMMENT '登录密码（PBKDF2-SHA256 哈希，格式 salt$hex）',
    role_type   VARCHAR(20)  DEFAULT 'USER'          COMMENT '角色标识：ADMIN / USER',
    create_time TIMESTAMP    DEFAULT CURRENT_TIMESTAMP COMMENT '注册时间'
) ENGINE=InnoDB COMMENT='全局用户与权限表';

-- -----------------------------------------------------------
-- 表 5：列车停靠站表 (train_stops) — 动态路由核心
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
-- 预置种子账户（密码均为 123456，使用 PBKDF2-SHA256 哈希存储）
-- 注：哈希值由 db_setup.py 的 _seed_users() 动态生成，此处硬编码用于纯 SQL 初始化场景。
-- -----------------------------------------------------------
INSERT IGNORE INTO users (user_id, username, password, role_type) VALUES
    ('U_ADMIN_001', 'admin',    '288052b09d64a961a42e4e5de7d70ae6$1f7343fb176383d4ade2b7975dc7ef396f40de16df06c961923ae8a42573cbe9', 'ADMIN'),
    ('U_PASS_001',  'zhangsan', '0a16b61920e16db5dc3acf48a4738190$b0185fe570548a62d3d2f8e0891cffde538d0c79d0023ebf59a268ccbb2f6345', 'USER');
