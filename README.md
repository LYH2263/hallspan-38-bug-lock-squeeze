# HallSpan 考场间距排座

在考室网格上按最小曼哈顿距离排座，同试卷套不得四邻相邻，并输出违规与统计。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4900 |
| API | http://localhost:9900 |
| API 文档 | http://localhost:9900/docs |
| Postgres | localhost:5450 |

健康检查：`GET http://localhost:9900/api/health`

## 使用说明

1. 在「考室」「考生」「试卷套」确认基础数据。
2. 打开「排座图」执行间距排座。
3. 在「违规」查看间距或同卷相邻问题。
4. 在「统计」查看占用与违规汇总。

## 锁定座位（保锁）

- 在「排座图」点击任一已坐格位即可 🔒 锁定/解锁；左侧名册同步标记。
- 再次排座时，被锁考生必须留在原格，其他人绕开锁格；新图、违规、统计与锁位保持一致。
- **保锁与拆锁硬排互斥**：若新约束（如调大「考室」最小曼哈顿间距）使锁位本身不再合法，整场排座失败（HTTP 409），方案列表不新增，锁位不会被拆掉硬排别人；页面保留上一张方案图。
- 解锁只改锁定状态、不立即重排；下一次排座起，原格才允许重排。
- 锁标记随每个方案以快照形式存入 `result_json`；当前解锁/重锁不会回刷历史方案。

## 开发与测试

```bash
docker compose exec api pytest -q
```
