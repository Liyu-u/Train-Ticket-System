# 🚄 极速抢票系统 — 数据库 Schema 文档

> **版本**: V3.2 (金融级流水账本)  
> **引擎**: InnoDB (事务 + 行级锁 + 外键约束)  
> **字符集**: utf8mb4  
> **数据库名**: train_ticket

---

## 一、表总览 (8 表 + 1 视图)

| # | 表名 | 用途 | 层级 |
|---|---|---|---|
| 1 | `train_models` | 车型基准费率字典 | 字典表 |
| 2 | `seat_classes` | 座位等级倍率字典 | 字典表 |
| 3 | `users` | 用户与权限 | 基础数据 |
| 4 | `train_info` | 列车基础信息 | 核心业务 |
| 5 | `train_stops` | 经停站时刻表 | 核心业务 |
| 6 | `seat_status` | 座位区间位图 | 核心业务 |
| 7 | `orders` | 交易订单 | 交易数据 |
| 8 | `transaction_logs` | 金融流水账本 | 审计追踪 |
| — | `v_daily_financial_report` | 财务大盘视图 | 分析视图 |

---

## 二、ER 关系图

```
┌──────────────────┐
│   train_models   │  字典：车型基准价
│  PK type_code    │  G=100, D=60, K=20 元/站
└────────┬─────────┘
         │ LEFT JOIN (type_code = LEFT(train_id,1))
         ▼
┌──────────────────┐       ┌──────────────────────┐
│    train_info    │ 1───N │     train_stops      │
│  PK train_id     │       │  PK id               │
│    train_no      │       │  FK train_id ────────┤
│    departure     │       │    station_name       │
│    arrival       │       │    stop_index (0,1,2) │
│    departure_time│       │    arrival_time       │
│    total_seats   │       │    departure_time     │
│    price ────────┼──┐    │  UNIQUE(train,stop)   │
└────────┬─────────┘  │    │  UNIQUE(train,station)│
         │             │    └──────────────────────┘
         │ 1───N       │
         ▼             │    ┌──────────────────────┐
┌──────────────────┐   │    │   transaction_logs   │
│   seat_status    │   │    │  PK log_id (AUTO)    │
│  PK seat_id      │   │    │    order_id ─────────┤
│  FK train_id ────┤   │    │    user_id ──────────┤
│    carriage_no   │   │    │    action_type       │
│    seat_no       │   │    │    amount            │
│    class_code ───┼───┼┐   │    create_time       │
│    seat_bitmap   │   ││   │  INDEX(order,user,   │
│    default_mask  │   ││   │         time)        │
│  UNIQUE(train,   │   ││   └──────────────────────┘
│    carr, seat)   │   ││          ▲
└────────┬─────────┘   ││          │ 1──N (按 order_id 关联)
         │ 1──N        ││          │
         ▼             ││   ┌──────┴───────────────┐
┌──────────────────┐   ││   │       orders         │
│  seat_classes    │   ││   │  PK order_id         │
│  PK class_code   │◄──┘│   │  FK user_id ─────────┤
│    class_name    │    │   │  FK train_id ────────┤
│  price_multiplier│    │   │  FK seat_id ─────────┤
│  SWZ=3.0 YDZ=1.6 │    │   │    buy_mask (INT)    │
│  EDZ=1.0         │    │   │    price (DECIMAL)   │
└──────────────────┘    │   │    order_status      │
                        │   │    status (1/2)      │
                        │   │    create_time       │
                        │   └──────────────────────┘
                        │              │
                        │  FK user_id  │
                        ▼              ▼
               ┌──────────────────────────┐
               │          users           │
               │  PK user_id              │
               │    username (UNIQUE)     │
               │    password (PBKDF2)     │
               │    role_type (ADMIN/USER)│
               │    create_time           │
               └──────────────────────────┘
```

---

## 三、逐表详细定义

### 1. `train_models` — 车型基准费率字典

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `type_code` | VARCHAR(10) | **PK** | 车型代码：`G` / `D` / `K` |
| `type_name` | VARCHAR(50) | NOT NULL | 车型名称：高铁 / 动车 / 普快 |
| `base_rate` | DECIMAL(10,2) | NOT NULL | 每站基准价（元） |

**种子数据**：

| type_code | type_name | base_rate |
|---|---|---|
| G | 高铁 | 100.00 |
| D | 动车 | 60.00 |
| K | 普快 | 20.00 |

---

### 2. `seat_classes` — 座位等级倍率字典

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `class_code` | VARCHAR(10) | **PK** | 席别代码：`SWZ` / `YDZ` / `EDZ` |
| `class_name` | VARCHAR(50) | NOT NULL | 席别名称 |
| `price_multiplier` | DECIMAL(4,2) | NOT NULL | 价格倍率 |

**种子数据**：

| class_code | class_name | price_multiplier |
|---|---|---|
| SWZ | 商务座 | 3.0 |
| YDZ | 一等座 | 1.6 |
| EDZ | 二等座 | 1.0 |

---

### 3. `users` — 用户与权限

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `user_id` | VARCHAR(50) | **PK** | 用户唯一 ID |
| `username` | VARCHAR(50) | NOT NULL, **UNIQUE** | 登录账号 |
| `password` | VARCHAR(256) | NOT NULL | PBKDF2-SHA256 哈希 (`salt$hex`) |
| `role_type` | VARCHAR(20) | DEFAULT 'USER' | `ADMIN` 或 `USER` |
| `create_time` | TIMESTAMP | DEFAULT NOW | 注册时间 |

**种子数据**：

| user_id | username | password | role_type |
|---|---|---|---|
| U_ADMIN_001 | admin | (哈希) | ADMIN |
| U_PASS_001 | zhangsan | (哈希) | USER |

> 明文密码均为 `123456`

---

### 4. `train_info` — 列车基础信息

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `train_id` | VARCHAR(20) | **PK** | 车次编号，如 `G101` |
| `train_no` | VARCHAR(20) | | 车次号，默认同 train_id |
| `departure` | VARCHAR(100) | NOT NULL | 始发站名 |
| `arrival` | VARCHAR(100) | NOT NULL | 终点站名 |
| `total_seats` | INT | NOT NULL | 总座位数 |
| `departure_time` | DATETIME | NOT NULL | 首发时间 |
| `price` | DECIMAL(10,2) | | **定价熔断字段**：>0 时覆盖自动定价 |

> **定价熔断逻辑**：`COALESCE(NULLIF(price, 0), models.base_rate, 100.00)`  
> 管理员设置 `price > 0` → 全系统使用此价格；`price = 0` → 按车型前缀自动定价。

**种子数据**：

| train_id | train_no | departure | arrival | departure_time | price | total_seats |
|---|---|---|---|---|---|---|
| G101 | G101 | 北京南 | 上海虹桥 | 2026-07-01 08:00 | 300.00 | 100 |

---

### 5. `train_stops` — 经停站时刻表 (动态路由核心)

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `id` | INT | **PK** AUTO_INCREMENT | 主键 |
| `train_id` | VARCHAR(20) | NOT NULL, **FK** → `train_info.train_id` | 所属车次 |
| `station_name` | VARCHAR(100) | NOT NULL | 车站名称 |
| `stop_index` | INT | NOT NULL | 经停序号 (从 0 开始)，**对应位图偏移量** |
| `arrival_time` | DATETIME | NULL | 到站时间（首站 NULL） |
| `departure_time` | DATETIME | NULL | 离站时间（末站 NULL） |

> - `UNIQUE (train_id, stop_index)` — 每站序号唯一
> - `UNIQUE (train_id, station_name)` — 每站名唯一
> - `ON DELETE CASCADE` — 删除车次时级联删除经停站

**种子数据 (G101)**：

| stop_index | station_name | arrival_time | departure_time |
|---|---|---|---|
| 0 | 北京南 | NULL | 2026-07-01 08:00 |
| 1 | 济南西 | 2026-07-01 10:30 | 2026-07-01 10:35 |
| 2 | 南京南 | 2026-07-01 13:00 | 2026-07-01 13:05 |
| 3 | 上海虹桥 | 2026-07-01 15:00 | NULL |

---

### 6. `seat_status` — 座位区间位图 (高并发核心)

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `seat_id` | INT | **PK** AUTO_INCREMENT | 座位全局唯一 ID |
| `train_id` | VARCHAR(20) | NOT NULL | 所属车次 |
| `carriage_no` | INT | NOT NULL | 车厢号 |
| `seat_no` | VARCHAR(10) | NOT NULL | 座位号，如 `01A` |
| `class_code` | VARCHAR(10) | DEFAULT 'EDZ' → `seat_classes.class_code` | 席别代码 |
| `seat_bitmap` | INT | DEFAULT 0 | **二进制区间占用状态**：0 = 全空闲 |
| `default_mask` | INT | DEFAULT 0 | 默认区间掩码 |

> - `UNIQUE (train_id, carriage_no, seat_no)` — 每座位唯一

**位图模型示例**（G101 有 4 个经停站 → 3 个区间，存储为位 bit0/bit1/bit2）：

```
seat_bitmap = 0b000  → 🟢 全空闲
seat_bitmap = 0b001  → 🔴 bit0 被占（北京南→济南西）
seat_bitmap = 0b010  → 🔴 bit1 被占（济南西→南京南）
seat_bitmap = 0b100  → 🔴 bit2 被占（南京南→上海虹桥）
seat_bitmap = 0b011  → 🔴 北京南→南京南 被占
seat_bitmap = 0b111  → 🔴 全程被占
```

**购票时**: `seat_bitmap = seat_bitmap | buy_mask` (OR 置位)  
**退票时**: `seat_bitmap = seat_bitmap ^ buy_mask` (XOR 清零)

**种子数据 (G101)**：25 个座位 (01A ~ 05F)，3+2 布局，按排号分级：

| 排号 | 列 | 座位数 | class_code | 倍率 |
|---|---|---|---|---|
| Row 1 | A, B, C, D, F | 5 | SWZ (商务座) | 3.0× |
| Row 2 | A, B, C, D, F | 5 | YDZ (一等座) | 1.6× |
| Row 3-5 | A, B, C, D, F | 15 | EDZ (二等座) | 1.0× |

车厢布局：`[A] [B] [C] |过道| [D] [F]`

---

### 7. `orders` — 交易订单

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `order_id` | VARCHAR(64) | **PK** | 订单流水号，格式 `ORDxxxxxxxxxx` |
| `user_id` | VARCHAR(64) | NOT NULL → `users.user_id` | 购票用户 |
| `train_id` | VARCHAR(20) | → `train_info.train_id` | 车次编号 |
| `seat_id` | INT | → `seat_status.seat_id` | 购买的座位 |
| `buy_mask` | INT | DEFAULT 0 | 本次购买的区间掩码 |
| `price` | DECIMAL(10,2) | DEFAULT 0 | 实付金额 |
| `order_status` | VARCHAR(20) | DEFAULT 'PAID' | `PAID` / `REFUNDED` |
| `status` | INT | DEFAULT 1 | `1=已支付` / `2=已退票` |
| `create_time` | TIMESTAMP | DEFAULT NOW | 下单时间 |

**状态流转**：

```
  [购票] → PAID (status=1)
              │
              ▼ [退票]
         REFUNDED (status=2)  ← 不可逆
```

**区间掩码反向解码**（前端 `my_orders` 展示真实行程用）：

```python
start_index = (buy_mask & -buy_mask).bit_length() - 1  # 最右 1 的位置
end_index   = buy_mask.bit_length()                      # 最左 1 的下一位
```

---

### 8. `transaction_logs` — 金融级流水账本 (审计追踪)

| 列 | 类型 | 约束 | 说明 |
|---|---|---|---|
| `log_id` | BIGINT | **PK** AUTO_INCREMENT | 流水主键 |
| `order_id` | VARCHAR(64) | NOT NULL | 关联订单号 |
| `user_id` | VARCHAR(64) | NOT NULL | 操作人 ID |
| `action_type` | VARCHAR(10) | NOT NULL | `PAY` (支付入账) / `REFUND` (退款支出) |
| `amount` | DECIMAL(10,2) | NOT NULL | 金额变动 |
| `create_time` | TIMESTAMP | DEFAULT NOW | 流水创建时间 |

> - `INDEX idx_order (order_id)` — 按订单追溯
> - `INDEX idx_user (user_id)` — 按用户审计
> - `INDEX idx_time (create_time)` — 按时间排序

**写入时机**：
- `POST /api/buy` 事务内 → INSERT `('PAY', actual_price)`
- `POST /api/refund` 事务内 → INSERT `('REFUND', refund_price)`
- 与 `orders` 和 `seat_status` 在同一事务中，**任一步失败全部回滚**

---

### 9. `v_daily_financial_report` — 财务大盘视图

```sql
CREATE OR REPLACE VIEW v_daily_financial_report AS
SELECT
    t.train_id,
    CURDATE() AS sale_date,
    COUNT(o.order_id)                                         AS total_orders,
    SUM(CASE WHEN o.status = 1 THEN 1 ELSE 0 END)             AS paid_orders,
    SUM(CASE WHEN o.status = 2 THEN 1 ELSE 0 END)             AS refunded_orders,
    COALESCE(SUM(CASE WHEN o.status = 1 THEN o.price ELSE 0 END), 0) AS total_sales,
    COALESCE(SUM(CASE WHEN o.status = 2 THEN o.price ELSE 0 END), 0) AS refund_amount,
    COALESCE(SUM(CASE WHEN o.status = 1 THEN o.price ELSE 0 END), 0) AS net_revenue
FROM train_info t
LEFT JOIN orders o ON t.train_id = o.train_id
GROUP BY t.train_id;
```

---

## 四、核心业务流程

### 4.1 定价熔断链（全系统统一）

```
COALESCE(NULLIF(train_info.price, 0), train_models.base_rate, 100.00)
     │                    │                    │              │
     ▼                    ▼                    ▼              ▼
管理员自定义 > 0      自定义 = 0 时        车型字典匹配      兜底值
  → 使用此价格          → 跳过此值         → G=100/D=60/K=20  → 100
```

**应用位置（5 处统一）**：

| # | 文件 | 函数/路由 | 用途 |
|---|---|---|---|
| 1 | `ticket_service.py` | `query_trains()` | 车次下拉框 `data-base-rate` |
| 2 | `ticket_service.py` | `query_seats()` | 座位图 `base_rate` |
| 3 | `webapp.py` | `GET /api/query_routes` (模式 A) | 模糊搜索路线 |
| 4 | `webapp.py` | `GET /api/query_routes` (模式 B) | 浏览全部路线 |
| 5 | `webapp.py` | `POST /api/buy` (步骤 4a) | 购票服务端计价 |

**最终票价公式**：

```
actual_price = DECIMAL(segment_count) × DECIMAL(base_rate) × DECIMAL(price_multiplier)
                .quantize(Decimal('0.00'))
```

### 4.2 购票事务流程 (`POST /api/buy`)

```
conn.begin()
  ├─ 1. SELECT ... FOR UPDATE (锁定 seat_status 行)
  ├─ 2. Python 内存冲突检测 (bitmap & mask) != 0 → rollback
  ├─ 3. UPDATE seat_status SET seat_bitmap = bitmap | mask (扣减库存)
  ├─ 4. 服务端二次计价 (不信任前端金额)
  │     ├─ COALESCE(NULLIF(ti.price,0), tm.base_rate, 100) → base_rate
  │     ├─ seat_classes.price_multiplier → multiplier
  │     └─ Decimal(segs) × Decimal(base_rate) × Decimal(multiplier) → actual_price
  ├─ 5. INSERT orders (order_id, ..., actual_price, 'PAID', 1)
  ├─ 6. INSERT transaction_logs (order_id, user_id, 'PAY', actual_price)
  └─ 7. COMMIT (任一步失败 → ROLLBACK 全部)
```

### 4.3 退票事务流程 (`POST /api/refund`)

```
conn.begin()
  ├─ 1. SELECT ... FOR UPDATE (锁定 orders 行，需 status='PAID')
  │     → owner_id, seat_id, buy_mask, refund_price
  ├─ 2. 权限校验 (ADMIN 全权 / USER 只能退自己的)
  ├─ 3. UPDATE orders SET status='REFUNDED', status=2
  ├─ 4. UPDATE seat_status SET seat_bitmap = bitmap ^ buy_mask (XOR 释放)
  ├─ 5. INSERT transaction_logs (order_id, owner_id, 'REFUND', refund_price)
  └─ 6. COMMIT (任一步失败 → ROLLBACK 全部)
```

### 4.4 智能路线检索

```
GET /api/query_routes?from_station=北京&to_station=上海

模式 A (有参数): LIKE %keyword% 模糊匹配
  SQL: s_start.station_name LIKE '%北京%'
   AND s_end.station_name   LIKE '%上海%'
   AND s_start.stop_index < s_end.stop_index

模式 B (无参数): 浏览全部
  SQL: s_first.stop_index = 0
   AND s_last.stop_index = MAX(stop_index)
```

---

## 五、API ↔ 表操作映射

| 路由 | 方法 | 写操作表 | 读操作表 |
|---|---|---|---|
| `/api/login` | POST | — | `users` |
| `/api/logout` | POST | — | session |
| `/api/trains` | GET | — | `train_info` ⨝ `train_models` |
| `/api/stops/<id>` | GET | — | `train_stops` |
| `/api/seats` | GET | — | `seat_status` ⨝ `seat_classes` ⨝ `train_info` ⨝ `train_models` |
| `/api/query_routes` | GET | — | `train_info` ⨝ `train_stops`×2 ⨝ `train_models` |
| `/api/get_train_schedule` | GET | — | `train_stops` |
| `/api/add_train` | POST | `train_info`, `train_stops`, `seat_status` | — |
| `/api/buy` | POST | `seat_status`, `orders`, **`transaction_logs`** | `train_info` ⨝ `train_models`, `seat_classes` |
| `/api/refund` | POST | `orders`, `seat_status`, **`transaction_logs`** | `orders` |
| `/api/my_orders` | GET | — | `orders` ⨝ `seat_status` ⨝ `train_stops` |
| `/api/financial` | GET | — | `v_daily_financial_report` |
| `/api/finance/logs` | GET | — | `transaction_logs` |

---

## 六、索引与外键

### 外键约束

| 子表 | 外键列 | 父表 | 规则 |
|---|---|---|---|
| `train_stops` | `train_id` | `train_info.train_id` | ON DELETE CASCADE |
| `orders` | `train_id` | `train_info.train_id` | 逻辑关联 (无硬约束) |
| `orders` | `seat_id` | `seat_status.seat_id` | 逻辑关联 (无硬约束) |
| `orders` | `user_id` | `users.user_id` | 逻辑关联 (无硬约束) |

> `orders` 表的外键使用逻辑关联（软引用），避免高并发下的锁升级问题。

### 唯一约束

| 表 | 约束 | 说明 |
|---|---|---|
| `users` | `UNIQUE(username)` | 账号不可重复 |
| `seat_status` | `UNIQUE(train_id, carriage_no, seat_no)` | 同一车次车厢座位号唯一 |
| `train_stops` | `UNIQUE(train_id, stop_index)` | 同一车次序号唯一 |
| `train_stops` | `UNIQUE(train_id, station_name)` | 同一车次站名唯一 |

### 普通索引

| 表 | 索引 | 说明 |
|---|---|---|
| `transaction_logs` | `idx_order (order_id)` | 按订单追溯流水 |
| `transaction_logs` | `idx_user (user_id)` | 按用户审计流水 |
| `transaction_logs` | `idx_time (create_time)` | 按时间排序 (LIMIT 100) |

---

## 七、重置脚本

```bash
# 幂等初始化（已有数据则跳过）
python db_setup.py

# 强制重建（DROP ALL + CREATE + INSERT 种子数据）
python db_setup.py --reset
```

**DROP 顺序**（先删子表再删父表）：

```
1. orders            (→ seat_status, train_info, users)
2. transaction_logs  (→ orders, users)
3. seat_status       (→ train_info)
4. train_stops       (→ train_info)
5. train_info
6. train_models
7. seat_classes
8. users
```
