## TrainTicketSystem 项目目录结构

```
TrainTicketSystem/
│
├── webapp.py                        Flask 后端主程序，启动入口
├── db_setup.py                      数据库初始化 + 测试固定数据
├── templates/index.html             前端单页应用
├── config/db_config.py              数据库连接工厂
├── services/ticket_service.py       票务查询服务
├── utils/db_helper.py               统一连接导出
├── requirements.txt                 Python 依赖清单
├── .env                             数据库连接配置
│
├── test_concurrency.py              并发购票压测脚本
├── 建表代码总结.md                    
├── 表.md                             
└── readme.md                        
```

------



## 核心文件说明

### `db_setup.py` — 数据库初始化

- `ensure_tables()` → 创建 **8 张表** + 1 个视图 + 2 个触发器
- `populate_sample_data()` → 事务写入固定测试数据G101 车次 + 4 个经停站 + 25 个分级座位 + 3 种车型字典 + 3 种席别字典 + 2 个用户
- `reset_all_data()` → DROP 全部表 + 触发器 → 重新建表 + 插入种子数据

```bash
python db_setup.py              # 幂等初始化
python db_setup.py --reset      # 强制重建
```

**8 张表**：`train_models`、`seat_classes`、`users`、`train_info`、`train_stops`、`seat_status`、`orders`、`transaction_logs`

**2 个触发器**：

- `trg_after_order_insert` — INSERT orders（status=1）→ 自动写入 transaction_logs（'PAY'）

- `trg_after_order_update` — UPDATE orders（status 1→2）→ 自动写入 transaction_logs（'REFUND'）

  

------

## 核心数据流

```
用户登录 → session[role_type] = ADMIN/USER
    │
    ├─ USER: #user-view
    │   ├─ 智能搜索 → /api/query_routes (LIKE 模糊 + COALESCE 定价)
    │   ├─ 预订联动 → /api/stops → 精准设站 → /api/seats (位图渲染)
    │   ├─ 一键抢票 → 支付弹窗 → /api/buy (事务: 锁→防超卖→计价→触发器记账)
    │   └─ 我的车票 → /api/my_orders (位运算反向解码真实行程)
    │
    └─ ADMIN: #admin-view 
        ├─ 发布车次 → /api/add_train (写 train_info + 25座 + 经停站)
        ├─ 车次看板 → /api/admin/trains (列表) + DELETE (级联删除)
        ├─ 财务大盘 → /api/financial (v_daily_financial_report 视图)
        └─ 流水明细 → /api/finance/logs (transaction_logs 倒序)
```



## 数据库操作

### 一、INSERT — 写入操作

#### 1.1 用户注册 → `users` 表

------

#### 1.2 发布新车次 → 三张表同时写入

------

#### 1.3 购票 → 触发器自动记账

------

### 二、DELETE — 删除操作

#### 2.1 管理员级联删除车次

------

### 三、UPDATE — 更新操作

#### 3.1 退票 → 位图 XOR 释放 + 触发器自动记退款

------

### 四、SELECT — 查询操作

#### 4.1 智能路线搜索（3 表 JOIN + LIKE 模糊）

------

#### 4.2 座位矩阵渲染（位图冲突实时检测）

------

#### 4.3 财务大盘（从视图读取）

------

#### 五、触发器 — 数据库层自动执行



## 总结

| 操作类型   | 涉及表                                          | 触发场景  | 写入方式                               |
| ---------- | ----------------------------------------------- | --------- | -------------------------------------- |
| **INSERT** | `users`                                         | 注册      | Python `api_register()`                |
| **INSERT** | `train_info` + `train_stops` + `seat_status`    | 发布车次  | Python `api_add_train()` 事务          |
| **INSERT** | `orders`                                        | 购票      | Python `api_buy()` 事务                |
| **INSERT** | `transaction_logs`                              | 购票/退票 | **MySQL 触发器自动写入**               |
| **UPDATE** | `orders`                                        | 退票      | Python `api_refund()` 事务             |
| **UPDATE** | `seat_status`（bitmap OR）                      | 购票      | Python `api_buy()` 事务                |
| **UPDATE** | `seat_status`（bitmap XOR）                     | 退票      | Python `api_refund()` 事务             |
| **DELETE** | `orders` + `seat_status` + `train_info`         | 删除车次  | Python `api_admin_delete_train()` 事务 |
| **SELECT** | `train_info` ⨝ `train_stops`×2 ⨝ `train_models` | 路线搜索  | `api_query_routes()`                   |
| **SELECT** | `seat_status` ⨝ `seat_classes` ⨝ `train_info`   | 座位矩阵  | `query_seats()`                        |
| **SELECT** | `v_daily_financial_report`                      | 财务大盘  | `api_financial()`                      |
| **SELECT** | `transaction_logs`                              | 流水明细  | `api_finance_logs()`                   |
