# NL2SQL 评测体系实现计划

## Context

项目是一个基于 LangGraph 的电商问数 Agent（NL2SQL），目前缺少量化评估手段——无法衡量 Agent 生成 SQL 的准确率、耗时和 Token 消耗，也无法对比优化前后的效果。本方案在 `feature/eval-set` 分支（worktree: `shop-query-eval-set`）上构建一套完整的评测体系：基于教学数仓 `dw.sql` 中的 5 张表设计 27 条测试用例，编写评测脚本批量调用 Agent 并以"执行结果一致"为标准判定对错，输出多维统计报告，支持按难度筛选与两次结果对比。

## 数据仓库现状（dw\.sql）

| 表              | 类型 | 关键字段                                                                                       | 行数           |
| -------------- | -- | ------------------------------------------------------------------------------------------ | ------------ |
| `dim_region`   | 维度 | region\_id, province, region\_name(华南/华东/西南/华北/华中), country                                | 6            |
| `dim_customer` | 维度 | customer\_id, customer\_name, gender(男/女), member\_level(黄金/白银/青铜/铂金)                      | 20           |
| `dim_product`  | 维度 | product\_id, product\_name, category(手机数码/家用电器/鞋靴/服饰/食品饮料/休闲零食), brand                     | 15           |
| `dim_date`     | 维度 | date\_id, year, quarter(Q1), month(1/2/3), day                                             | 90 (2025-Q1) |
| `fact_order`   | 事实 | order\_id, customer\_id, product\_id, date\_id, region\_id, order\_quantity, order\_amount | 120          |

## 评测用例清单（共 27 条，待确认）

### 简单（10 条）— 单表查询、简单聚合

| ID  | 自然语言问题         | 预期 SQL                                           | 涉及表/字段                      |
| --- | -------------- | ------------------------------------------------ | --------------------------- |
| E01 | 共有多少个客户？       | `SELECT COUNT(*) FROM dim_customer`              | dim\_customer               |
| E02 | 共有多少种商品？       | `SELECT COUNT(*) FROM dim_product`               | dim\_product                |
| E03 | 所有商品一共有哪些分类？   | `SELECT DISTINCT category FROM dim_product`      | dim\_product.category       |
| E04 | 客户的会员等级都有哪些？   | `SELECT DISTINCT member_level FROM dim_customer` | dim\_customer.member\_level |
| E05 | 一共有哪些省份？       | `SELECT DISTINCT province FROM dim_region`       | dim\_region.province        |
| E06 | 总共有多少笔订单？      | `SELECT COUNT(*) FROM fact_order`                | fact\_order                 |
| E07 | 所有订单的销售总金额是多少？ | `SELECT SUM(order_amount) FROM fact_order`       | fact\_order.order\_amount   |
| E08 | 所有订单的销售总数量是多少？ | `SELECT SUM(order_quantity) FROM fact_order`     | fact\_order.order\_quantity |
| E09 | 最高的一笔订单金额是多少？  | `SELECT MAX(order_amount) FROM fact_order`       | fact\_order.order\_amount   |
| E10 | 平均订单金额是多少？     | `SELECT AVG(order_amount) FROM fact_order`       | fact\_order.order\_amount   |

### 中等（10 条）— 多表 JOIN、分组排序

| ID  | 自然语言问题         | 预期 SQL（要点）                                                      | 涉及表/字段                     |
| --- | -------------- | --------------------------------------------------------------- | -------------------------- |
| M01 | 各商品分类的销售额是多少？  | fact\_order ⋈ dim\_product，GROUP BY category，SUM(order\_amount) | fact\_order, dim\_product  |
| M02 | 各会员等级的消费总额是多少？ | fact\_order ⋈ dim\_customer，GROUP BY member\_level              | fact\_order, dim\_customer |
| M03 | 各地区的订单数量是多少？   | fact\_order ⋈ dim\_region，GROUP BY region\_name，COUNT           | fact\_order, dim\_region   |
| M04 | 销售额排名前5的商品是哪些？ | JOIN 后 GROUP BY product\_name，ORDER BY SUM DESC LIMIT 5         | fact\_order, dim\_product  |
| M05 | 各省份的销售总额是多少？   | fact\_order ⋈ dim\_region，GROUP BY province                     | fact\_order, dim\_region   |
| M06 | 各品牌的销售数量是多少？   | fact\_order ⋈ dim\_product，GROUP BY brand，SUM(quantity)         | fact\_order, dim\_product  |
| M07 | 各月份的订单数量是多少？   | fact\_order ⋈ dim\_date，GROUP BY month，ORDER BY month           | fact\_order, dim\_date     |
| M08 | 各性别的消费总额是多少？   | fact\_order ⋈ dim\_customer，GROUP BY gender                     | fact\_order, dim\_customer |
| M09 | 每个季度的销售总额是多少？  | fact\_order ⋈ dim\_date，GROUP BY quarter                        | fact\_order, dim\_date     |
| M10 | 订单数量最多的客户是谁？   | JOIN 后 GROUP BY customer\_name，ORDER BY COUNT DESC LIMIT 1      | fact\_order, dim\_customer |

### 复杂（7 条）— 子查询、窗口函数、多条件

| ID  | 自然语言问题                | 预期 SQL（要点）                                                                                   | 涉及表/字段                                 |
| --- | --------------------- | -------------------------------------------------------------------------------------------- | -------------------------------------- |
| H01 | 哪些商品的销售额高于全部商品的平均销售额？ | 子查询：外层 GROUP BY product\_name HAVING SUM > (子查询 SELECT AVG(SUM) FROM (GROUP BY product\_id)) | fact\_order                            |
| H02 | 没有下过订单的客户有哪些？         | LEFT JOIN dim\_customer ⋈ fact\_order WHERE order\_id IS NULL                                | dim\_customer, fact\_order             |
| H03 | 每个商品分类中销售额最高的商品是什么？   | ROW\_NUMBER() OVER (PARTITION BY category ORDER BY SUM DESC) 取 rn=1                          | fact\_order, dim\_product              |
| H04 | 各地区销售额占总销售额的百分比是多少？   | 子查询：SUM(amount)\*100 / (SELECT SUM(amount) FROM fact\_order)                                 | fact\_order, dim\_region               |
| H05 | 各月份销售额及环比增长率          | LAG() OVER (ORDER BY month) 计算环比                                                             | fact\_order, dim\_date                 |
| H06 | 消费金额排名前3的客户（含并列）      | DENSE\_RANK() OVER (ORDER BY SUM DESC) <= 3                                                  | fact\_order, dim\_customer             |
| H07 | 同时在华南和华东都有销售的商品分类有哪些？ | 子查询 IN：华南的分类 ∩ 华东的分类                                                                         | fact\_order, dim\_product, dim\_region |

> 用例完整 SQL（含别名/窗口函数细节）将写入 `app/scripts/eval_cases.yaml`。

## 评测脚本架构

### 文件结构

```
app/scripts/
├── run_eval.py            # 评测主脚本（CLI 入口）
├── eval_cases.yaml        # 27 条评测用例数据集
└── eval_results/          # 评测结果输出目录（加入 .gitignore）
    └── eval_20260811_153000.json
```

### 关键设计

**1. 调用 Agent 的方式** — 复用 [graph.py](file:///f:/code/ai/shop-query-eval-set/app/agent/graph.py) `__main__` 与 [query\_service.py](file:///f:/code/ai/shop-query-eval-set/app/services/query_service.py) 的初始化模式：直接初始化 6 个 client manager（qdrant/embedding/es/meta\_mysql/dw\_mysql），构建 `DataAgentContext`，调用 `graph.astream(input=state, context=context, stream_mode="custom")`，收集 `{"type": "result", "data":..., "sql":...}` chunk。**绕过 Redis 缓存**（不走 QueryService），确保每次都测试真实 Agent 能力。

**2. 结果对比逻辑**（执行结果一致，非 SQL 文本对比）：

* 先用 `DWMySQLRepository.run()` 执行预期 SQL → expected\_result（`list[dict]`）

* 执行 Agent 生成的 SQL → actual\_result

* 归一化：float 四舍五入到 2 位（处理 FLOAT 精度），每行转成「按值排序的 tuple」（忽略列名/别名差异，对齐 Spider EX 指标）

* 行顺序不敏感：对两边的行 tuple 列表各自排序后比较（`sorted` multiset 对比）

* 行数必须一致 + 值集合一致 → 判定 PASS

* 可选 `--strict-order` 开关：要求行顺序也一致（用于排名类查询）

* 预期 SQL 自身报错时标记 `expected_sql_error`，不计入准确率分母（视为用例缺陷）

**3. Token 消耗统计** — 实现 `TokenTrackingCallback(BaseCallbackHandler)`，挂载到 [llm.py](file:///f:/code/ai/shop-query-eval-set/app/agent/llm.py) 的 `llm` 单例（`llm.callbacks = [handler]`）。在 `on_llm_end` 中从 `response.llm_output["token_usage"]` 读取（OpenAI 兼容协议），回退到累加 `gen.message.usage_metadata`，聚合一次评测内所有 LLM 调用（extract\_keywords/generate\_sql/validate\_sql/correct\_sql/filter\_\* 等多节点）的 prompt\_tokens/completion\_tokens/total\_tokens。读取失败时优雅降级为 N/A。

**4. 统计指标**：

* 总准确率 = 通过数 / 有效用例数

* 各难度准确率（easy/medium/hard）

* 平均耗时（秒）、总耗时

* Token 消耗：总 prompt/completion/total tokens、平均每条 tokens

**5. 输出**：

* **控制台表格**：每条用例显示 ID/难度/问题/结果(✓✗)/耗时/Token；末尾汇总统计

* **JSON 结果文件**：`eval_results/eval_{timestamp}.json`，含每个用例的 question/difficulty/expected\_sql/generated\_sql/expected\_result/actual\_result/passed/elapsed/tokens/error

* **失败用例详情**：JSON 中失败用例含完整 expected\_sql vs generated\_sql 及结果差异

**6. 两次评测对比** — `compare` 子命令：加载两个 JSON 结果文件，输出准确率差值、Token 差值、耗时差值，以及逐用例的状态变化（regression: 通过→失败 / improvement: 失败→通过 / unchanged）。

### CLI 接口

```bash
# 运行全部用例
python -m app.scripts.run_eval

# 只跑某个难度
python -m app.scripts.run_eval --difficulty medium

# 只跑指定用例
python -m app.scripts.run_eval --cases E01,M01

# 指定输出文件 + 严格顺序对比
python -m app.scripts.run_eval --strict-order --output my_run.json

# 对比两次评测结果
python -m app.scripts.run_eval compare --old eval_results/eval_xxx.json --new eval_results/eval_yyy.json
```

参数说明：`--difficulty {easy,medium,hard}`、`--cases ID列表`、`--output 路径`、`--strict-order`、`--conf 配置路径`（默认 `conf/app_config.yaml`）。

## 实现步骤

1. **创建** **`app/scripts/eval_cases.yaml`** — 写入 27 条用例（id/question/expected\_sql/difficulty/tables 字段）
2. **创建** **`app/scripts/run_eval.py`** — 实现：

   * 用例加载（YAML）

   * 客户端初始化（复用 build\_meta\_knowledge.py 模式）

   * `TokenTrackingCallback` 类

   * `run_single_case()`：执行预期 SQL + 调用 Agent + 对比

   * `compare_results()`：结果归一化与对比

   * `aggregate_stats()`：统计聚合

   * `print_report()`：控制台表格输出

   * `save_report()`：JSON 落盘

   * `compare_runs()`：两次结果对比

   * argparse CLI 入口
3. **更新** **`.gitignore`** — 添加 `app/scripts/eval_results/`

## 复用的现有代码

* [graph.py](file:///f:/code/ai/shop-query-eval-set/app/agent/graph.py) — `graph` 编译入口与 `__main__` 初始化模式

* [state.py](file:///f:/code/ai/shop-query-eval-set/app/agent/state.py) — `DataAgentState(query=...)`

* [context.py](file:///f:/code/ai/shop-query-eval-set/app/agent/context.py) — `DataAgentContext` 组装

* [dw\_mysql\_repository.py](file:///f:/code/ai/shop-query-eval-set/app/repositories/mysql/dw/dw_mysql_repository.py) — `run(sql)` 返回 `list[dict]`，用于执行预期 SQL 与生成 SQL

* [build\_meta\_knowledge.py](file:///f:/code/ai/shop-query-eval-set/app/scripts/build_meta_knowledge.py) — 客户端初始化与关闭的脚本模板

* [llm.py](file:///f:/code/ai/shop-query-eval-set/app/agent/llm.py) — `llm` 单例，挂载 token 回调

## 前置条件（运行评测时需要）

* Docker 服务已启动（MySQL/Qdrant/ES/Embedding/Redis），通过 `docker/docker-compose.yaml`

* 元数据知识库已构建（运行过 `python -m app.scripts.build_meta_knowledge -c conf/app_config.yaml`），否则 Agent 召回链路无数据

* `.env` 中 `LLM_API_KEY` 已配置

## 验证方式

1. **用例自检**：先单独跑 `python -m app.scripts.run_eval --cases E01` 验证脚本链路通畅，预期 SQL 能执行、Agent 能返回结果
2. **单难度跑通**：`python -m app.scripts.run_eval --difficulty easy` 确认 10 条简单用例的准确率与报告输出
3. **全量评测**：`python -m app.scripts.run_eval` 跑完 27 条，检查 JSON 结果文件完整性
4. **对比功能**：修改一处 prompt 后重跑，用 `compare` 子命令对比两次结果，确认 regression/improvement 识别正确
5. **失败用例检查**：在 JSON 中查看失败用例的 generated\_sql vs expected\_sql，确认对比逻辑合理

