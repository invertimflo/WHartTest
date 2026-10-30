# LLM 对话 / 用例生成「页面卡死」性能分析报告

> 版本：v1.0
> 范围：`WHartTest_Vue`（前端）+ `WHartTest_Django`（后端）`agent_loop` 全链路
> 触发场景：接入本地思考模型 `qwen3.8-flash-next`（上下文窗口 50k）后，LLM 对话任务与测试用例生成过程中页面较高概率卡死

---

## 1. 摘要（TL;DR）

页面"卡死"不是单一 bug，而是 **三层问题叠加**的结果：

| 层 | 核心问题 | 表现 |
|---|---|---|
| 浏览器渲染层 | 每个流式增量都触发「全列表 diff + 全量 Markdown 重解析 + 强制同步布局」 | 标签页无响应、输入框无法输入、滚动卡顿 |
| 前后端传输层 | 无心跳、无空闲检测、无总时长上限 | 长时间的"思考静默"与"连接已死"无法区分；nginx `proxy_read_timeout 600s` 到点直接断连 |
| 后端事件循环层 | 同步 ORM / tiktoken 计算 / 连接池创建直接跑在事件循环里 | 单个请求把整个 uvicorn worker 卡住，**所有会话一起挂** |

其中第 3 层最致命：Django 单 worker 部署下，一个慢请求会让整个服务失去响应，前端表现出来就是"卡死"。第 1 层是"看起来卡死"，第 3 层是"真的卡死"。

---

## 2. 问题现象与复现

### 2.1 现象

1. 发送一条需要多步工具调用的对话（如"读取需求文档 → 生成用例"），页面在执行过程中失去响应。
2. 输入框键入无反应，滚动条拖不动，刷新页面才恢复。
3. 模型长时间"思考"（无任何输出）时，页面一直停在 loading，最终弹 `network error`。
4. 一个会话卡住时，**其他会话的新消息也发不出去**（这一条是判断后端阻塞的关键信号）。

### 2.2 复现条件

| 条件 | 说明 |
|---|---|
| 模型 | 本地部署思考模型，首 token 延迟可达 60~180s，单轮输出每秒 5~15 个 token |
| 工具 | 触发 3 步以上工具调用（MCP 工具 / 知识库检索 / Playwright） |
| 上下文 | 会话历史 > 30 条，或单条工具输出 > 100KB（如 Playwright 快照、SQL 查询结果） |
| 部署 | `uvicorn --workers 1`，前端 `vite build` 生产包 |

### 2.3 最小复现步骤

```
1. 打开 LLM 对话页，选择本地思考模型
2. 上传一份需求文档，输入"根据文档生成 20 条测试用例"
3. 观察：Agent 开始调用工具 → 第 2~3 步时页面开始明显掉帧
4. 此时新开一个会话发一句"hi" → 若无响应，确认后端事件循环已被阻塞
5. 观察后端日志：出现长段空白（无 access log），随后一次性刷出多条
```

---

## 3. 请求链路与观测方法

### 3.1 全链路

```
浏览器
  │ fetch(POST /api/orchestrator/agent-loop/stream)
  ▼
nginx  ── proxy_buffering off / proxy_read_timeout 600s
  ▼
uvicorn (ASGI, 默认 1 worker)
  ▼
AgentLoopStreamAPIView.post
  ├── 拉取 LLM 配置 / 文件引用 / MCP 配置 / 内置工具 / 中间件   ← 大量同步 ORM
  ├── create_agent(...)  +  AsyncPostgresSaver（checkpointer）
  └── StreamingHttpResponse(async_generator)
        └── agent.astream(stream_mode=["updates","messages"])
              └── openai SDK → httpx → 本地推理服务
  ▼
SSE: data: {"type":"token", ...}\n\n
```

### 3.2 观测手段

| 观测点 | 方法 | 说明 |
|---|---|---|
| 前端渲染耗时 | Chrome Performance 面板 → 录制 30s 流式过程 | 看 `Recalculate Style` / `Layout` 是否有 >100ms 的长任务 |
| 前端事件循环阻塞 | Performance 面板中 `Task` 长条 | 单帧 >50ms 即为卡顿，>200ms 用户可感知 |
| SSE 帧频率 | DevTools Network → EventStream | 观察每秒帧数，修复前实测可达 30~60 帧/秒 |
| 后端事件循环滞后 | 本次新增 `[LoopLag]` 日志 | `sse_guard` 定时器漂移超过 `AGENT_LOOP_LAG_WARN_MS`(300ms) 即告警 |
| Django ORM 串行 | 日志时间戳连续性 | 同步调用串行到敏感线程时，不同会话的时间戳会呈现"排队"特征 |

---

## 4. 根因分析

按「前端渲染 → 前端状态机 → 传输层 → 后端事件循环 → 后端资源 → 重试语义」六层展开。

### 4.1 前端渲染层：每个 token 都在重建整棵消息树

#### 根因 A1：列表 key 使用数组下标

**代码定位**：`WHartTest_Vue/src/features/langgraph/components/ChatMessages.vue`（修复前 `:key="index"`）

**机理**：流式过程中最新一条 AI 消息的内容持续变化，而 `messages` 数组每次 flush 都会被重新构造。配合 `:key="index"`，Vue 会把"下标相同但实际是另一条消息"的节点判为同一个，同时又因为父数组重建导致 `v-for` 重新执行 diff。结果是**整个列表的 vnode 全部重新比对**，历史消息参与 diff 但不该重渲染。

**后果**：消息数 N 时，每帧 O(N) 次 diff；N=50、每秒 40 帧时，每秒 2000 次组件比对，主线程直接饱和。

#### 根因 A2：流式正文每次 flush 全量重新解析 Markdown

**代码定位**：`MessageItem.vue` `formattedContent` / `formatToolMessage`（`marked` + `DOMParser` + `DOMPurify` + `v-html`）

**机理**：`marked()` 是 O(内容长度) 的完整解析，且每次输出一个新的 HTML 字符串，`v-html` 随之整体替换 DOM 子树。流式正文从 100 字涨到 5000 字的过程中，累计解析量是 **O(n²)**——第 k 个 token 到来时要把前 k-1 个 token 重新解析一遍。

**后果**：单这条就足以让长回答（>3000 字）产生秒级卡顿。工具输出（大 JSON）走同一条路径，单次解析可达 200ms+。

#### 根因 A3：无论流式帧多密都直接触发渲染

**代码定位**：`chatService.ts` 中 `createStreamFlushThrottle`（修复前仅 50ms 兜底）

**机理**：后端每个 token 一帧 SSE，前端每帧都写响应式状态。Vue 的调度器会合并同一 tick 内的多次写入，但 SSE 帧间隔本身 > 16ms，等于**每个 token 都换来一次完整渲染**。

#### 根因 A4：`deep watch` 监听整个流对象

**代码定位**：`LangGraphChatView.vue`（修复前 `watch(activeStreams, ..., { deep: true })`）

**机理**：深度监听会对整个 stream 对象做递归遍历，其中包含 `messages` 数组、base64 截图 `imageDataUrl`、完整工具输出。每次 flush 都要把这个大对象完整走一遍并建立依赖。

**后果**：单次遍历耗时随上下文线性增长，且和 A1/A2 叠加放大。

#### 根因 A5：长会话历史消息全部参与布局

**代码定位**：`ChatMessages.vue` 容器 CSS

**机理**：所有历史消息节点都在布局树里，工具消息的 `<pre>` 块高度巨大。每次插入新内容都会触发整页 reflow。

#### 根因 A6：超长工具输出无护栏

**代码定位**：`MessageItem.vue` `formatToolMessage`

**机理**：Playwright 快照、大 SQL 结果可能达到数 MB。一次性格式化 + 高亮 + 插入 DOM，单次操作即造成 >1s 的阻塞。

---

### 4.2 前端状态机：loading 无法收敛

#### 根因 B1：`start` 事件前失败导致永久 loading

**代码定位**：`chatService.ts` `handleError`

**机理**：`activeStreams[sessionId]` 在收到 `start` 事件（携带 `session_id`）后才创建。若在 `start` 之前就失败（网络错误、后端 500、鉴权失败），清理逻辑找不到对应的 stream 条目，`isLoading` 永远停在 `true`——**从用户视角就是"卡死"**，而且连报错信息都没有。

#### 根因 B2：无空闲超时，静默等待无上界

**代码定位**：`chatService.ts` `readStream`

**机理**：`reader.read()` 会一直挂着等。思考模型 180s 不出首 token 时，前端没有任何反馈，也没有超时放弃。用户只能刷新。

#### 根因 B3：切换会话时 loading 状态串台

**代码定位**：`LangGraphChatView.vue` `switchSession` / `createNewChat`

**机理**：`isLoading` 是页面级单例。会话 A 正在流式输出时切到会话 B，`isLoading` 仍为 `true`，B 的输入框被锁死。反之，从 A 切回 B 也可能被 A 的状态影响。

---

### 4.3 传输层：静默期与死亡期无法区分

#### 根因 C1：SSE 无心跳

**机理**：思考模型在 reasoning 阶段可能长时间不产生可见 token。此时后端不写任何字节，前端 `reader.read()` 挂起，nginx 也收不到数据。

**后果**：
- nginx `proxy_read_timeout 600s` 到点**直接断开**，前端收到 `network error`，而实际上后端还在正常推理。
- 前端没有任何"还活着"的信号，无法区分"模型在想"和"连接已死"。
- 用户看到的唯一反馈是转圈，且转圈不代表任何真实状态。

#### 根因 C2：无总时长上限

**机理**：`recursion_limit` 只限制步数（弱模型 160 / 强模型 1000），不限制实际耗时。一步工具调用耗时 10 分钟时，步数没涨但连接已经挂了很久。

#### 根因 C3：`resume` 流缺少停止信号检查

**代码定位**：`agent_loop_view.py` `AgentLoopResumeAPIView`（修复前 `astream` 循环内无 `should_stop` 检查）

**机理**：从 HITL 审批恢复的流不响应"停止"按钮，用户点了停止但后端继续跑，前端连接不断，表现为"点了没反应"。

---

### 4.4 后端事件循环层：真正的"服务级卡死"

#### 根因 D1：`sync_to_async` 默认 `thread_sensitive=True`，全进程串行

**代码定位**：`agent_loop_view.py` 中原有大量 `sync_to_async(func)(...)` 调用

**机理**：`thread_sensitive=True` 会把**整个进程内所有请求**的同步调用编排到同一个"敏感线程"上串行执行。任一 ORM 查询慢 2 秒，其它会话的 `validate_file_ids`、`get_builtin_tools`、`get_middleware_from_config` 全部排队。

**后果**：这就是"一个会话卡住，所有会话都发不出消息"的直接原因。

#### 根因 D2：`calculate_context_tokens` 同步阻塞事件循环

**代码定位**：`agent_loop_view.py` `calculate_context_tokens`（`_calculate_overhead_tokens` + 逐条消息内容遍历估算）

**机理**：该函数在 `astream` 循环内部被调用，且**直接在协程里同步执行**，没有 `await to_thread`。它会遍历整个上下文的消息内容做 token 估算，上下文 50k 时单次耗时可达 100~300ms。

**后果**：每个流式步骤都阻塞一次事件循环。由于它是纯 CPU 计算，阻塞期间**所有协程（含其它会话的 SSE 心跳）全部停摆**。

#### 根因 D3：checkpointer 每请求新建连接池且重复跑 DDL

**代码定位**：`wharttest_django/checkpointer.py`

**机理**（修复前）：
- 每个请求 `AsyncConnectionPool(...)` 新建一个池并 `await pool.open()`；
- 每次 `await saver.setup()` 执行建表 DDL。`setup()` 内部虽有 `CREATE TABLE IF NOT EXISTS`，但仍需拿 advisory lock，多个请求并发时排队等待。

**后果**：连接数随并发线性增长直到打满 PostgreSQL `max_connections`；`setup()` 的 lock 等待直接叠加到首 token 延迟上。

#### 根因 D4：配置与工具装配在事件循环内同步执行

**代码定位**：`agent_loop_view.py` `get_builtin_tools` / `get_middleware_from_config` / `RemoteMCPConfig.objects.filter(...)`

**机理**：这些函数内部做多次 DB 查询（MCP 配置、工具审批、知识库绑定），且在原实现中同步执行于协程上下文。

#### 根因 D5：每条对话都读一次 `LLMConfig`

**代码定位**：`agent_loop_view.py` 中 `LLMConfig.objects.get(is_active=True)`

**机理**：热路径上的纯读取，每条对话一次查询多一次往返。

---

### 4.5 后端超时与重试语义

#### 根因 E1：单一超时数值同时作用于 connect / read / write

**代码定位**：`langgraph_integration/views.py` `create_llm_instance`

**机理**（修复前）：传单一 `request_timeout` 给 httpx。httpx 会把它当成所有分项的超时。connect 阶段本该 5~10s 快速失败，却要等满整个 300s；而 write 阶段也可能被异常拉长。

**后果**：连接层故障无法快速暴露，前端白等；同时 read 超时如果设得不够长，思考模型正常推理也会被判超时。

#### 根因 E2：SDK 重试与中间件重试叠加，重试次数被放大

**代码定位**：`langgraph_integration/views.py`（openai SDK `max_retries`）+ `middleware_config.py`（`ModelRetryMiddleware`）

**机理**：openai SDK 默认 `max_retries=2`，`ModelRetryMiddleware` 又做一层重试。两者相乘，最坏情况下一次用户请求实际发起 **3×N** 次上游调用。

**后果**：本地模型本就慢，重试放大直接把响应时间推到不可接受；同时并发连接数暴涨，加重后端 D2/D3 的阻塞。

#### 根因 E3：重试时已下发的 token 无法撤回

**代码定位**：`middleware_config.py` `_retry_should_retry`

**机理**：模型输出到一半断连触发重试，前端已经渲染了前半段文本。重试后新内容追加在后面，用户看到的是**重复、错乱、语义不连贯**的回答。这不是"卡死"，但会被用户描述为"页面乱掉了"。

---

## 5. 根因链路图

```
用户点击发送
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│ 后端：AgentLoopStreamAPIView.post                            │
│                                                              │
│  D1 sync_to_async(thread_sensitive=True)                     │
│      └─► 全进程敏感线程串行 ──┐                              │
│  D2 calculate_context_tokens  │  同步阻塞事件循环            │
│  D4 get_builtin_tools         │  ──► 所有协程停摆            │
│  D3 checkpointer pool+setup   │      （含其它会话）          │
│  D5 LLMConfig.objects.get   ──┘                              │
└─────────────────────────────────────────────────────────────┘
      │  事件循环被长时间占用
      ▼
┌─────────────────────────────────────────────────────────────┐
│ SSE 传输层                                                   │
│  C1 无心跳 ──► 前端无法区分"思考中" / "已断连"               │
│            └─► nginx proxy_read_timeout 600s 到点强制断开    │
│  C2 无总时长上限 ──► 单请求理论上可无限挂起                  │
│  C3 resume 无停止检查 ──► 停止按钮失效                       │
└─────────────────────────────────────────────────────────────┘
      │  每秒 30~60 帧 SSE
      ▼
┌─────────────────────────────────────────────────────────────┐
│ 前端渲染层                                                   │
│  A1 :key="index"        ──► O(N) 次节点 diff                │
│  A2 marked 全量重解析   ──► O(n²) 累计解析量                 │
│  A4 deep watch 大对象   ──► 每帧深遍历 base64/大 JSON        │
│  A3 无节流              ──► 每个 token 一次完整渲染          │
│  A5 无 content-visibility ─► 全历史参与布局                  │
│  A6 无大输出护栏        ──► 单次 >1s 阻塞                    │
│                          ↓                                   │
│                    主线程饱和 → 页面无响应                    │
└─────────────────────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────────────────────┐
│ 前端状态机                                                   │
│  B1 start 前失败 ──► 永久 loading，连报错都没有              │
│  B2 无空闲超时   ──► 无限等待                                │
│  B3 切会话串台   ──► 输入框被误锁                            │
└─────────────────────────────────────────────────────────────┘
```

---

## 6. 修复方案与对照表

修复原则：**先止血（前端不再因为流式增量而重渲染），再解阻塞（后端不再阻塞事件循环），最后补韧性（心跳、超时、重试、可插拔部署）**。

### 6.1 前端渲染止血

| 编号 | 根因 | 修复措施 | 位置 |
|---|---|---|---|
| A1 | 下标 key | `WeakMap` 生成稳定 key（`keyOf`）；流式尾部固定 `'__stream_tail__'`；配合 `v-memo="memoOf(message)"` | `ChatMessages.vue` |
| A2 | 全量 Markdown 重解析 | 正文 < 1200 字走**纯文本插值**（跳过 marked/DOMPurify）；≥ 1200 字改 **400ms 快照节奏**；完成瞬间一次性渲染最终 Markdown | `StreamingBubble.vue`、`MessageItem.vue` |
| A2 | 历史消息重复解析 | `formattedCache: { key, html }` 弱缓存，key 由 `messageType/isUser/isStreaming/isLoading/content` 拼接 | `MessageItem.vue` |
| A3 | 帧频率过高 | `MIN_FLUSH_INTERVAL_MS = 60` 强制最小间隔；`FALLBACK_FLUSH_MS` 50→80；关键事件走 `flushNow()` 立即写入 | `chatService.ts` |
| A4 | deep watch | 改为精确监听 `activeStreams[sid].isComplete` 单值 | `LangGraphChatView.vue` |
| A5 | 全历史布局 | `content-visibility: auto` + `contain-intrinsic-size: auto 120px` | `ChatMessages.vue` |
| A6 | 大输出无护栏 | `MAX_TOOL_FORMAT_CHARS = 200_000`，超限截断并提示 | `MessageItem.vue` |
| 新增 | 流式内容与历史列表耦合 | 抽出 `StreamingBubble.vue` 独立渲染流式尾部，不再进入 `messages` 数组；父组件拆为 `historyMessages` + `currentStream` | 新增组件 |

### 6.2 前端状态机修复

| 编号 | 根因 | 修复措施 | 位置 |
|---|---|---|---|
| B1 | 永久 loading | 新增 `ensureStreamEntry()`，任何失败路径都保证 stream 条目存在并能被清理；`handleStreamMessage` 加 `try/catch/finally` | `chatService.ts`、`LangGraphChatView.vue` |
| B2 | 无空闲超时 | 内部 `AbortController` + 分阶段看门狗：`FIRST_BYTE_TIMEOUT_MS = 150s`（首字节）、`IDLE_TIMEOUT_MS = 45s`（帧间隔）；外部 signal 转发 | `chatService.ts` |
| B3 | 切会话串台 | `syncLoadingFromStream(id)`：按**目标会话自己的流状态**恢复 `isLoading`；`createNewChat` 归位为 `false`；明确**不 abort** 后台流（各会话独立 AbortController） | `LangGraphChatView.vue` |

### 6.3 传输层韧性

| 编号 | 根因 | 修复措施 | 位置 |
|---|---|---|---|
| C1 | 无心跳 | `guarded_sse()` 包装层，默认 10s 一帧 `{"type":"heartbeat","idle_s":n,"phase":"model\|tool\|summarizing"}` | 新增 `sse_guard.py` |
| C1 | 静默无区分 | 分阶段空闲看门狗：模型阶段 240s、工具阶段 900s 无进展即下发 `stream_idle_timeout`（code 504） | `sse_guard.py` |
| C2 | 无总时长上限 | `AGENT_LOOP_TOTAL_DEADLINE`（默认 1800s），超限下发 `stream_total_timeout` | `sse_guard.py` |
| C2 | 非流式同样无上限 | 非流式分支接入同一看门狗，`AGENT_LOOP_NON_STREAM_TIMEOUT`（默认 600s） | `agent_loop_view.py` |
| C3 | resume 无停止检查 | `AgentLoopResumeAPIView.astream` 循环内补 `ashould_stop` / `aclear_stop_signal` | `agent_loop_view.py` |
| 新增 | 断连不取消上游 | `finally` 中 `task.cancel()` + `await inner.aclose()`，确保 LLM 请求真正中断，不再空转烧算力 | `sse_guard.py` |
| 新增 | 事件循环卡顿无感知 | 定时器漂移检测，超过 `AGENT_LOOP_LAG_WARN_MS`(300ms) 打 `[LoopLag]` 日志 | `sse_guard.py` |

### 6.4 后端事件循环解阻塞

| 编号 | 根因 | 修复措施 | 位置 |
|---|---|---|---|
| D1 | 敏感线程串行 | 新增 `_offload()`（`thread_sensitive=False`），改造 14 处同步调用：`validate_file_ids`、`build_llm_attachment_context`、`_load_active_llm_config`、`create_llm_instance`、MCP 配置列表、`create_knowledge_tool`、`get_builtin_tools`（主流 + resume）、`get_middleware_from_config`（两处）、`get_user_tool_approvals`（两处） | `agent_loop_view.py` |
| D1 | 跨线程惰性 QuerySet | MCP 配置查询改为 `lambda: list(...)`，避免 QuerySet 在非创建线程求值 | `agent_loop_view.py` |
| D2 | CPU 计算阻塞 | `calculate_context_tokens` 改为 `await asyncio.to_thread(...)`（主流 + resume 两处） | `agent_loop_view.py` |
| D3 | 连接池风暴 + 重复 DDL | 进程级共享 `AsyncConnectionPool`（`max_size=10`、`timeout=10`）；`setup()` 用 `pg_advisory_lock(hashtext('langgraph_checkpoint_setup'))` 保证只跑一次；失败自动降级到每请求模式；事件循环变更时重建池 | `checkpointer.py` |
| D4 | 工具装配阻塞 | 同 D1，统一走 `_offload` | `agent_loop_view.py` |
| D5 | 配置热路径读 | 30s TTL 进程内缓存 + `post_save`/`post_delete` 信号失效 | `agent_loop_view.py`、`apps.py` |

### 6.5 超时与重试语义

| 编号 | 根因 | 修复措施 | 位置 |
|---|---|---|---|
| E1 | 单一超时 | 拆为 `httpx.Timeout(connect=10, read=max(request_timeout,300), write=60, pool=connect)`，全部可用环境变量覆盖 | `langgraph_integration/views.py` |
| E1 | 兼容性 | `ChatQwen` 若不接受 `httpx.Timeout` 对象，`except TypeError` 回退为数值超时 | `langgraph_integration/views.py` |
| E2 | 重试放大 | openai SDK `max_retries` 由 `min(db_retries, LLM_CLIENT_MAX_RETRIES)` 决定，**默认 0**，重试权收归 middleware 单点 | `langgraph_integration/views.py` |
| E3 | 重试文本重复 | 新增 `stream_progress` 记录"本轮是否已下发 token"；重试时推送 `stream_reset` 事件，前端清空已渲染正文并提示"模型输出中断，正在重新生成…" | 新增 `stream_progress.py`、`middleware_config.py`、`chatService.ts` |

### 6.6 部署可扩展性（保留开关，默认单进程）

| 项 | 默认 | 开关 | 说明 |
|---|---|---|---|
| uvicorn worker 数 | 1 | `UVICORN_WORKERS` | 多 worker 需同时满足 Redis 停止信号 + Redis channel layer |
| 停止信号后端 | memory | `AGENT_STOP_BACKEND=redis` | 多 worker 下 memory 后端只能停掉处理该请求的进程 |
| Channel layer | memory | `CHANNEL_LAYER_BACKEND=redis` | WebSocket 广播跨进程必需 |
| checkpointer 共享池 | 开启 | `AGENT_CHECKPOINTER_SHARED=0` 关闭 | 关闭后回到每请求建池 |

> 多 worker 前置条件已写入 `supervisord.conf` 注释，避免误配。

---

## 7. 改动文件清单

### 后端新增

| 文件 | 作用 |
|---|---|
| `WHartTest_Django/orchestrator_integration/sse_guard.py` | SSE 心跳 / 分阶段空闲看门狗 / 总时长上限 / 断连取消 / 事件循环卡顿检测 |
| `WHartTest_Django/orchestrator_integration/stream_progress.py` | 记录本轮是否已下发 token，供重试去重使用 |
| `WHartTest_Django/orchestrator_integration/management/commands/run_fake_llm.py` | 假慢速思考模型服务（OpenAI 兼容），可控首 token 延迟 / 逐字速度 / 中途静默 / 中途断连 / 上游错误 |
| `scripts/sse_load.py` | 并发 SSE 压测与观测：首帧延迟、帧间隔 p50/p95/max、心跳计数、停止验证 |

### 后端修改

| 文件 | 改动要点 |
|---|---|
| `orchestrator_integration/agent_loop_view.py` | `_offload` 改造 14 处；LLM 配置 TTL 缓存；`guarded_sse` 接线主流 + resume + 非流式；`calculate_context_tokens` 转线程；resume 补停止信号；`stream_progress` 标记与清理 |
| `orchestrator_integration/middleware_config.py` | `get_model_retry_middleware` 新增 `session_id`，重试时推送 `stream_reset` |
| `orchestrator_integration/stop_signal.py` | 重写为 memory / redis 双后端，新增异步接口 `aset_stop_signal` / `ashould_stop` / `aclear_stop_signal`，保留同步接口兼容 |
| `orchestrator_integration/apps.py` | `LLMConfig` 增删时失效配置缓存 |
| `wharttest_django/checkpointer.py` | 共享连接池 + `setup()` 单次执行 + 失败降级 + 事件循环变更重建 |
| `wharttest_django/settings.py` | `CHANNEL_LAYERS` 支持 `CHANNEL_LAYER_BACKEND=memory\|redis` |
| `langgraph_integration/views.py` | httpx 分项超时；SDK `max_retries` 归零；`ChatQwen` 超时类型兼容 |
| `supervisord.conf` | `--workers ${UVICORN_WORKERS:-1} --timeout-keep-alive 75` |
| `requirements.txt` | 显式声明 `psycopg-pool==3.3.3` |

### 前端新增

| 文件 | 作用 |
|---|---|
| `src/features/langgraph/components/StreamingBubble.vue` | 流式气泡独立渲染单元：纯文本 / Markdown 快照双模式、"模型思考中（已等待 N 秒）"等活跃提示 |
| `src/views/testcase/components/GenerationTaskPanel.vue` | 用例生成常驻进度面板，支持取消 / 查看对话 / 清除 |

### 前端修改

| 文件 | 改动要点 |
|---|---|
| `features/langgraph/components/ChatMessages.vue` | 稳定 key + `v-memo`；`stream` prop 接入 `StreamingBubble`；滚动合并到 rAF；`content-visibility`；`active` prop 支持 keep-alive 后台静默 |
| `features/langgraph/components/MessageItem.vue` | 删除 3 处 `:key="message.content"`；Markdown 弱缓存；大工具输出护栏；`plainText` 纯文本快路径 |
| `features/langgraph/services/chatService.ts` | flush 节流；`ensureStreamEntry`；首字节 / 空闲双看门狗；`heartbeat` / `phase` / `stream_reset` 事件处理 |
| `features/langgraph/views/LangGraphChatView.vue` | `historyMessages` + `currentStream` 拆分；精确 watch 替代 deep watch；`switchSession` / `createNewChat` 的 loading 同步；`onDeactivated` 静默 |
| `views/TestCaseManagementView.vue` | 用例生成任务状态管理 + 进度面板 + 取消能力 |

---

## 8. 新增配置项

全部有合理默认值，**不配置也能正常工作**。

### 8.1 SSE 守护

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `AGENT_LOOP_SSE_GUARD` | `1` | 总开关，设为 0 完全退回旧行为 |
| `AGENT_LOOP_HEARTBEAT_INTERVAL` | `10` | 心跳帧间隔（秒） |
| `AGENT_LOOP_MODEL_IDLE_TIMEOUT` | `240` | 模型阶段无进展超时（秒） |
| `AGENT_LOOP_TOOL_IDLE_TIMEOUT` | `900` | 工具阶段无进展超时（秒） |
| `AGENT_LOOP_TOTAL_DEADLINE` | `1800` | 单轮流式总时长上限（秒） |
| `AGENT_LOOP_NON_STREAM_TIMEOUT` | `600` | 非流式请求总时长上限（秒） |
| `AGENT_LOOP_LAG_WARN_MS` | `300` | 事件循环卡顿告警阈值（毫秒） |

### 8.2 LLM 客户端

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `LLM_CONNECT_TIMEOUT` | `10` | 连接超时（秒） |
| `LLM_READ_TIMEOUT` | 跟随请求超时（≥300） | 读取超时（秒），思考模型需放宽 |
| `LLM_WRITE_TIMEOUT` | `60` | 写超时（秒） |
| `LLM_POOL_TIMEOUT` | 同 connect | 连接池取连接超时（秒） |
| `LLM_CLIENT_MAX_RETRIES` | `0` | SDK 层重试上限，默认关掉避免与中间件叠加 |
| `LLM_CONFIG_CACHE_TTL` | `30` | LLM 配置缓存 TTL（秒），0 表示不缓存 |

### 8.3 检查点与部署

| 环境变量 | 默认 | 说明 |
|---|---|---|
| `AGENT_CHECKPOINTER_SHARED` | `1` | 进程级共享连接池开关 |
| `AGENT_CHECKPOINTER_POOL_SIZE` | `10` | 连接池大小 |
| `AGENT_CHECKPOINTER_POOL_TIMEOUT` | `10` | 取连接超时（秒） |
| `AGENT_STOP_BACKEND` | `memory` | `memory` / `redis` |
| `AGENT_STOP_TTL` | `300` | Redis 停止信号 TTL（秒） |
| `CHANNEL_LAYER_BACKEND` | `memory` | `memory` / `redis` |
| `UVICORN_WORKERS` | `1` | worker 数 |

### 8.4 慢模型推荐配置

`qwen3.8-flash-next` 这类本地思考模型建议：

```bash
# 放宽模型阶段空闲判定，避免"还在思考"被误判超时
AGENT_LOOP_MODEL_IDLE_TIMEOUT=600
AGENT_LOOP_TOOL_IDLE_TIMEOUT=1200
AGENT_LOOP_TOTAL_DEADLINE=3600
AGENT_LOOP_HEARTBEAT_INTERVAL=10

# 读取超时同步放宽
LLM_READ_TIMEOUT=900
```

同时确认 nginx `proxy_read_timeout`（当前 `600s`）**大于** `AGENT_LOOP_HEARTBEAT_INTERVAL`，否则心跳还没发出就被断开。当前配置 10s ≪ 600s，安全。

---

## 9. 验证与回归清单

### 9.1 已完成的验证

| 项 | 方法 | 结果 |
|---|---|---|
| `sse_guard` 心跳 | 假生成器，`heartbeat_interval=0.4` | 实测 0.41s 间隔，符合预期 |
| `sse_guard` 空闲超时 | 假生成器停顿，`model_idle=0.6` | 0.62s 触发 `stream_idle_timeout` |
| `sse_guard` 总时长超时 | 慢速持续产出，`deadline=1` | 正确下发 `stream_total_timeout` |
| `sse_guard` 内层异常 | 生成器抛异常 | 正确转为 `stream_internal_error` 帧，不断连 |
| `stream_progress` | 标记 / 消费 / 清理 | 语义正确，一次性消费 |
| 后端语法 | `python -m py_compile` 全部改动文件 | 通过 |
| 前端类型 | `npx vue-tsc --noEmit -p tsconfig.app.json` | 无错误 |
| 前端构建 | `npx vite build` | 成功（47.02s） |
| 假模型服务可达性 | `GET /v1/models` | 正常返回模型列表 |
| 假模型 + openai SDK 流式 | `client.chat.completions.create(stream=True)` | 收到 5 个 delta，文本完整，`finish_reason="stop"` 正常收尾 |
| 假模型 + openai SDK 非流式 | 同上 `stream=False` | 返回完整 content + usage（195 tokens） |
| 假模型 + `--fail-after 3` | 模拟上游中途断连 | **SDK 未抛异常**，仅收到 3 个 chunk 后正常结束（详见第 12 节遗留风险） |

### 9.2 待完成的回归（需要可用运行环境）

`manage.py check` 当前受环境阻塞：`mcp` 包版本与 `langchain-mcp-adapters` 不兼容（`cannot import name 'RequestContext' from 'mcp.shared.context'`）。这是**改动前就存在的环境问题**，与本次变更无关，需先修复依赖再跑完整回归。

| 场景 | 预期 |
|---|---|
| 思考模型 3 分钟无 token | 前端 10s 一跳心跳，显示"模型思考中（已等待 N 秒）…"，页面可滚动、可输入 |
| 模型中途断连 | 自动重试；已渲染内容被清空并提示"正在重新生成…"，不出现重复文本 |
| 手动停止（主流） | 立即下发 `stopped`，加载态收敛 |
| 手动停止（HITL resume 流） | 同样立即停止（本次修复） |
| 切会话（A 在流式中 → 切 B） | A 后台继续，B 输入框立即可用；切回 A 续显进度 |
| 切页面（keep-alive） | 后台不再排队 rAF 滚动，CPU 占用明显下降 |
| 用例生成 20 条 | 右下角进度面板显示步数与耗时，可取消 |
| 超长工具输出（>200KB） | 截断展示并提示，不卡顿 |
| 并发 2 个会话同时流式 | 互相不阻塞（D1 修复的核心验收点） |
| 发送后立刻断网 | 45s 内报"连接已中断"，loading 收敛 |

### 9.3 压测与复现工具（已提供）

排查这类问题必须有可控的"坏模型"，否则只能靠运气等线上复现。本次提供两个零额外依赖的工具：

#### `run_fake_llm.py` — 假慢思考模型（OpenAI 兼容）

```bash
# 模拟思考模型：首 token 等 180s
python manage.py run_fake_llm --first-token-delay 180

# 中途静默 300s（验证心跳 + 空闲看门狗）
python manage.py run_fake_llm --silent-after 50 --silent-for 300

# 第 200 个 chunk 后断连（验证重试 + stream_reset）
python manage.py run_fake_llm --fail-after 200

# 上游直接 500（验证错误文案映射）
python manage.py run_fake_llm --status 500

# 超长输出压测
python manage.py run_fake_llm --total-chunks 5000 --chunk-interval 0.02
```

把 LLM 配置的 `base_url` 指向 `http://127.0.0.1:8100/v1`、`api_key` 随意填、模型名填 `fake-thinking-model` 即可接入真实链路（openai SDK → httpx → agent_loop → SSE）。

> 该命令的 `requires_system_checks = []`，因此**即使 URLconf 被第三方包版本问题阻塞也能启动**——性能排查往往正是在这种环境下进行。

#### `scripts/sse_load.py` — 并发 SSE 压测

```bash
# 10 路并发，统计首帧延迟 / 帧间隔 / 心跳数
python scripts/sse_load.py --token <JWT> --project-id 1 --concurrency 10

# 第 20 秒发停止请求，验证停止信号
python scripts/sse_load.py --token <JWT> --project-id 1 --concurrency 3 --stop-after 20
```

输出每路的 frames / heartbeats / 首帧延迟 / p95 与 max 帧间隔，并对异常直接给出提示：

- `max gap > 30s` → 心跳未生效或事件循环被同步调用卡住
- 长连接但 `heartbeats == 0` → `guarded_sse` 未接上或 `AGENT_LOOP_SSE_GUARD=0`
- 多路并发时首帧延迟**同时**变长 → 基本可确认是事件循环 / 敏感线程阻塞（D1/D2 未修复时的典型特征）

---

## 10. 回滚方案

所有改动都有独立开关，可分级回滚，无需改代码：

```bash
# 1. 关闭 SSE 守护（心跳/看门狗全部失效，回到旧行为）
AGENT_LOOP_SSE_GUARD=0

# 2. 关闭 checkpointer 共享池
AGENT_CHECKPOINTER_SHARED=0

# 3. 关闭 LLM 配置缓存
LLM_CONFIG_CACHE_TTL=0

# 4. 回到单进程 + 内存停止信号
UVICORN_WORKERS=1
AGENT_STOP_BACKEND=memory
CHANNEL_LAYER_BACKEND=memory
```

前端改动（`StreamingBubble` / `v-memo` / 节流）属于纯渲染优化，不改变 SSE 协议与数据结构，可独立保留；`heartbeat` / `phase` / `stream_reset` 三个新事件是**增量事件**，旧前端收到会走 `default` 分支忽略，**协议向后兼容**。

---

## 11. 后续建议（本次未实施）

| 优先级 | 建议 | 理由 |
|---|---|---|
| P1 | 修复 `mcp` 与 `langchain-mcp-adapters` 版本冲突 | 阻塞 `manage.py check` 与端到端联调 |
| P1 | 静默截断检测（见第 12 节） | 上游中途断连目前**不会**报错，回答会被静默截短 |
| P2 | 前端引入虚拟滚动（只渲染可视区消息） | 千条以上超长会话的终极方案 |
| P2 | 流式正文改为增量 Markdown（只解析新增片段） | 进一步降低长回答的解析成本 |
| P2 | 把 `LLMConfig` 缓存改为 Redis 共享缓存 | 多 worker 部署后进程内缓存不再一致 |
| P3 | SSE 从 GET/POST 迁移到 WebSocket（已有 channels 依赖） | 双向通信，HITL 审批交互更自然 |

---

## 12. 遗留风险：上游中途断连会被"静默吞掉"

### 12.1 现象（已实测确认）

用假模型的 `--fail-after 3` 模拟上游在第 3 个 chunk 后直接关闭连接，再用 openai SDK 消费：

```
[abrupt-disconnect] OK chunks=3 elapsed=0.30s text=这是一段用于压测的模拟模
```

**没有异常，没有报错**——SDK 把它当成了流正常结束。

### 12.2 影响

1. `ModelRetryMiddleware` **不会触发**，因为异常根本没抛出来；
2. `agent_loop` 会正常走完流程，向前端下发 `done`；
3. 用户看到一条**语义完整但被砍断**的回答（例如测试用例只生成了一半），并且界面上没有任何异常提示；
4. 这类问题极具迷惑性：用户反馈是"模型生成不完整"，而不是"报错"，很难被归因到网络故障。

### 12.3 为什么本次没有直接改

可靠的判定信号只有 `finish_reason`：正常结束为 `stop`，被截断时为 `None`。但**部分本地推理服务（vLLM / 部分 Qwen 部署）本身就不返回 `finish_reason`**，若直接据此判定，会把正常回答全部标成"截断"，反而制造大面积误报。

### 12.4 建议的实现方式

在 `astream` 循环结束处做**带开关的软提示**，而不是硬报错：

```python
# 伪代码
TRUNCATION_GUARD = os.getenv("AGENT_LOOP_TRUNCATION_GUARD", "0")  # 默认关，按模型实测后开启

if TRUNCATION_GUARD and streamed_tokens and last_ai_message:
    finish = (last_ai_message.response_metadata or {}).get("finish_reason")
    has_usage = bool(getattr(last_ai_message, "usage_metadata", None))
    if finish is None and not has_usage:
        yield create_sse_data({
            "type": "warning",
            "code": "stream_maybe_truncated",
            "message": "模型输出可能未完整结束（上游连接提前关闭），建议重新生成",
        })
```

要点：
- **默认关闭**，先在目标模型上跑一遍确认 `finish_reason` 的实际取值，再打开；
- 用 `warning` 而非 `error`，不中断流程、不改变已渲染内容；
- 同时以 `not has_usage` 作为辅助条件，降低不返回 `finish_reason` 的模型被误判的概率。

### 12.5 验证方法

```bash
# 终端 1：断连模型
python manage.py run_fake_llm --port 8100 --first-token-delay 0.2 --fail-after 3

# 终端 2：观察后端是否识别
python scripts/sse_load.py --token <JWT> --project-id 1 --concurrency 1

# 预期（开启 guard 后）：event_types 中出现 warning，且会话里能看到提示
```
