-- 创建并使用数据库
CREATE DATABASE IF NOT EXISTS train_ticket DEFAULT CHARSET utf8mb4;
use train_ticket;
-- 表 1：列车车次表 (Train Info)
CREATE TABLE train_info (
    train_id VARCHAR(20) PRIMARY KEY COMMENT '车次编号，如 G101',
    start_station VARCHAR(50) NOT NULL COMMENT '始发站',
    end_station VARCHAR(50) NOT NULL COMMENT '终点站',
    total_seats INT NOT NULL COMMENT '总座位数',
    departure_time DATETIME NOT NULL COMMENT '发车时间'
) ENGINE=InnoDB COMMENT='列车基础信息表';

-- 表 2：座位状态表 (Seat Status) - 核心炫技点！
CREATE TABLE seat_status (
    seat_id INT AUTO_INCREMENT PRIMARY KEY,
    train_id VARCHAR(20) NOT NULL,
    carriage_no INT NOT NULL COMMENT '车厢号',
    seat_no VARCHAR(10) NOT NULL COMMENT '座位号，如 01A',
    seat_bitmap INT DEFAULT 0 COMMENT '二进制区间状态：0代表全路段未售',
    UNIQUE KEY uk_train_seat (train_id, carriage_no, seat_no) -- 防止同一座位重复录入
) ENGINE=InnoDB COMMENT='高并发座位区间状态表';

-- 表 3：订单交易表 (Orders)
CREATE TABLE orders (
    order_id VARCHAR(50) PRIMARY KEY COMMENT '订单流水号',
    user_id VARCHAR(50) NOT NULL COMMENT '购票用户ID',
    train_id VARCHAR(20) NOT NULL,
    seat_id INT NOT NULL,
    buy_mask INT NOT NULL COMMENT '本次购买的区间掩码',
    order_status VARCHAR(20) DEFAULT 'PAID' COMMENT '状态：PAID(已支付), REFUNDED(已退票)',
    create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB COMMENT='交易订单表';