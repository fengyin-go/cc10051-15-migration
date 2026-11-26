# 主数据治理与参考数据管理平台

覆盖主数据抽取、标准化清洗、去重合并、金记录发布与下游订阅分发的治理平台

这是一个前后端分离的管理平台：前端 Vue 3 + Vite + TypeScript，后端 FastAPI（Python）。
两边各自独立启动，前端 dev server 已关掉自动打开页面，启动后按终端打印的地址手工打开。

## 目录结构

```text
.
├── frontend/                 Vue 3 + Vite + TypeScript 前端
│   ├── src/views/WorkbenchView.vue|tsx  全部模块共享工作台
│   ├── src/data/modules.ts              18个业务模块配置
│   ├── src/api/              统一请求封装
│   └── vite.config.ts        dev server 配置（open: false）
├── backend/                  FastAPI（Python） 后端
│   ├── app/routers/resource.py  通用查询/导出/登记/动作接口
│   ├── app/services/<key>.py    每个模块独立领域逻辑
│   ├── app/services/base.py     共享服务骨架
│   └── app/store.py          内存数据仓库与示例数据
├── .gitignore
└── docker-compose.yml
```

## 启动

### 后端

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
./run.sh
```

健康检查：`curl http://127.0.0.1:8021/api/health`

### 前端

```bash
cd frontend
npm ci
npm run dev
```

前端默认监听 `http://127.0.0.1:5201/`，dev server 不会自动打开浏览器，
需要自己访问。`/api` 由 vite 代理到后端 `http://127.0.0.1:8021`。

## 业务模块

| 模块 | 目录 | 业务对象 | 主要字段 |
| --- | --- | --- | --- |
| 源系统登记 | `source_system` | 源系统 | 系统标识、系统名称、数据域 |
| 主数据实体 | `entity_model` | 实体定义 | 实体编码、实体名称、唯一键规则 |
| 记录抽取作业 | `record_extract` | 抽取作业 | 作业名称、源系统、实体编码 |
| 标准化清洗 | `std_cleanse` | 清洗规则 | 规则名称、实体编码、清洗阶段 |
| 重复检测器 | `dup_detect` | 检测结果 | 检测批次、实体编码、候选组数 |
| 金记录合并 | `golden_merge` | 合并任务 | 合并任务、实体编码、候选组 |
| 金记录发布 | `golden_publish` | 发布批次 | 发布批次、实体编码、金记录数 |
| 下游订阅方 | `subscriber_mgr` | 订阅方 | 订阅方标识、订阅实体、分发格式 |
| 分发任务 | `dist_task` | 分发批次 | 分发批次、订阅方、记录范围 |
| 血缘关系图 | `lineage_graph` | 血缘边 | 血缘边标识、上游节点、下游节点 |
| 质量规则库 | `quality_rule` | 质量规则 | 规则名称、实体编码、检查维度 |
| 质量报告 | `quality_result` | 质量结果 | 报告批次、实体编码、检查总数 |
| 合并复核队列 | `merge_review` | 复核记录 | 记录编号、候选组、复核结论 |
| 版本回滚器 | `version_rollback` | 回滚任务 | 回滚任务、目标版本、回滚原因 |
| 同步游标 | `sync_cursor` | 游标记录 | 源系统、实体编码、游标值 |
| 标识交叉映射 | `id_cross_map` | 交叉映射 | 映射批次、源系统标识、金记录标识 |
| 分发回执中心 | `dist_receipt` | 回执记录 | 回执编号、分发批次、订阅方 |
| 实体变更审批 | `model_change` | 变更单 | 变更单号、实体编码、变更内容 |
| 治理看板数据 | `stats_overview` | 统计快照 | 统计时间、实体编码、金记录数 |
| 参考数据管理 | `ref_data_mgr` | 参考数据集 | 数据集编码、数据集名称、码值条目 |

## 约定

- 全部模块共享`frontend/src/views/WorkbenchView.vue|tsx`和一套资源路由。
- 每个模块仍保留独立`backend/app/services/<模块>.py`；纯前端保留
  `frontend/src/domain/<模块>.ts`，用于承载真实业务差异并维持36题位容量。
- 列表接口统一返回 `{ items, total, page, size }`，动作接口统一返回 `{ ok, message }`。
- 状态流转只允许在 `app/services` 里改，路由层不做业务判断。

## 码表版本化（JSON 条目格式）

旧码表用逗号分隔、等号切分（`CN=中国,US=美国`），业务值自带 `=`/`,`（如 `A=B`）
时无法判明边界。码表已迁移到带版本号的 JSON 条目格式，能力如下：

- 后端
  - `app/services/code_table_format.py`：旧格式/JSON 条目解析、迁移与回退判定。
    无歧义好行继续转换；多等号、缺等号、空值、重复码等坏行进拒收清单，
    保留原文与原因，绝不静默丢值；特殊字符版本转回旧结构时整体阻断。
  - `app/services/code_table_service.py` + 路由 `/api/code-tables/*`：
    登记、迁移报告、发布（不可变完整版本快照，版次独立递增）、版本回滚、
    运行时模式切换（模拟新版部署/旧版回滚）、清洗领用、归一化、批次复算、
    拒收条目查询。
  - 清洗批次按码表编号领用服务端当前发布版次，整版快照复制进批次记录并锁定：
    发布交接/回滚期间不拼装新旧条目，同批次重复领用返回同一快照。
  - 旧版应用回滚后，含特殊字符的 JSON 版本领用得到明确阻断回执
    （`reason=legacy_incompatible_special_chars`）；旧结构兼容版本自动降级为
    `码=值,码=值` 下发。历史版本原编号保留，旧批次可凭领用记录复算。
- 前端
  - 参考数据管理页（`ref_data_mgr`）挂 `RefDataPanel.vue`：登记普通值/特殊值、
    查看迁移拒收坏行、发布、版本列表与回滚、运行时切换。
  - 标准化清洗页（`std_cleanse`）挂 `CleansePanel.vue`：按码表编号领取批次码表、
    阻断回执展示、归一化、历史批次复算、领用记录核查。
- 测试（后端启动后）：
  - `.venv/bin/python -m unittest tests.test_code_table_format`（解析器单元测试）
  - `.venv/bin/python -m unittest tests.test_code_table_e2e`（全链路 HTTP 场景）

领域：数据工程
子方向：数仓与数据湖
