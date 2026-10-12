# UI自动化执行器 (WHartTest Actuator)

独立的UI自动化执行器服务，通过WebSocket连接Django后端，接收并执行自动化测试任务。

## 架构设计


```
┌─────────────┐     WebSocket      ┌──────────────────┐
│   Django    │ ◄────────────────► │   Actuator       │
│   Backend   │                    │   (执行器)        │
│             │                    │                  │
│ - Consumer  │ ◄─ 发送任务 ────── │ - WebSocketClient│
│ - 任务分发   │ ◄─ 返回结果 ────── │ - TaskConsumer   │
└─────────────┘                    │ - Executor       │
                                   └──────────────────┘
                                          │
                                          ▼
                                   ┌──────────────────┐
                                   │  Playwright      │
                                   │  (浏览器自动化)   │
                                   └──────────────────┘
```

## 通信协议

### 消息格式 (SocketDataModel)
```json
{
    "code": 200,
    "msg": "success",
    "user": "username",
    "is_notice": 2,
    "data": {
        "func_name": "u_test_case",
        "func_args": {
            "case_id": 1
        }
    }
}
```

### 支持的任务类型
- `u_page_steps` - 执行页面步骤
- `u_test_case` - 执行测试用例
- `u_test_case_batch` - 批量执行用例
- `u_stop_execution` - 停止执行
- `u_step_result` - 步骤执行结果
- `u_case_result` - 用例执行结果

## 安装

```bash
cd WHartTest_Actuator
pip install -r requirements.txt
```

## 使用

### 基本启动
```bash
python main.py
```

### 指定服务器地址
```bash
python main.py --server ws://192.168.1.100:8000/ws/ui/actuator/
```

### 指定执行器ID
```bash
python main.py --id actuator-01 --server ws://localhost:8000/ws/ui/actuator/
```

### 完整参数
```bash
python main.py \
    --server ws://localhost:8000/ws/ui/actuator/ \
    --api http://localhost:8000 \
    --id my-actuator \
    --log-level DEBUG
```

## 参数说明

| 参数 | 短参数 | 默认值 | 说明 |
|------|--------|--------|------|
| --server | -s | ws://localhost:8000/ws/ui/actuator/ | WebSocket服务器地址 |
| --api | -a | http://localhost:8000 | API服务器地址 |
| --id | -i | actuator-{pid} | 执行器唯一标识 |
| --log-level | -l | INFO | 日志级别 |

## 工作流程

1. **连接服务器**: 执行器启动后通过WebSocket连接Django后端
2. **等待任务**: 监听来自服务器的执行任务
3. **获取详情**: 通过REST API获取用例/步骤详细信息
4. **生成脚本**: 将步骤配置转换为Playwright代码
5. **执行测试**: 调用Playwright执行浏览器自动化
6. **返回结果**: 通过WebSocket将执行结果发送回服务器

## 打包成独立 EXE

执行器支持打包成独立可执行文件，方便分发部署。

### 安装打包依赖

```bash
# 使用 uv
uv pip install pyinstaller

# 或使用 pip
pip install pyinstaller
```

### 执行打包

```bash
cd WHartTest_Actuator
uv run python build_exe.py
```

### 输出目录

```
dist/WHartTest_Actuator/
├── WHartTest_Actuator.exe  # 主程序
├── config.toml             # 配置文件
├── start.bat               # GUI模式启动脚本
├── start_no_gui.bat        # 无GUI模式启动脚本
├── browsers/               # Playwright浏览器（首次运行自动下载）
└── data/                   # 数据目录
    ├── browser/            # 浏览器用户数据
    ├── screenshots/        # 截图
    └── traces/             # Trace文件
```

### 使用说明

1. 将 `dist/WHartTest_Actuator/` 目录复制到目标机器
2. 编辑 `config.toml` 配置服务器地址和账号
3. 双击 `start.bat` 启动（GUI模式）或 `start_no_gui.bat`（无GUI模式）

**首次运行**：
- 首次运行会自动下载 Chromium 浏览器（约 150MB）
- 浏览器会下载到 `browsers/` 目录
- 后续运行无需重复下载

## 分布式部署

执行器支持分布式部署，多个执行器可以同时连接到一个Django后端：

```bash
# 机器A
python main.py --id actuator-machine-a --server ws://server:8000/ws/ui/actuator/

# 机器B  
python main.py --id actuator-machine-b --server ws://server:8000/ws/ui/actuator/

# 机器C
python main.py --id actuator-machine-c --server ws://server:8000/ws/ui/actuator/
```

服务器会自动将任务分发给可用的执行器。

## HTTPS 客户端证书（双向 TLS 站点）

访问要求**客户端证书**的 HTTPS 站点（内网自签名双向 TLS 等）时，**无需在执行器上做任何配置**：
在 Web 端「接口自动化 / UI 自动化 → 环境管理 → 客户端证书」中按项目统一上传并保管证书，
再把它绑定到 UI 自动化环境即可。使用执行器执行该环境下的用例时，平台会随任务下发证书配置，
执行器自动下载并注入 Playwright。

- 证书文件由平台「文件管理」托管；执行器经带鉴权的下载接口拉取到本地缓存（校验 sha256），
  不再需要本机路径或 `certs/` 目录挂载。
- 口令只经「平台 → 执行器」的 WebSocket 通道下发，不落盘、不回传前端、不写入日志。
- 生效 origin 由环境的基础 URL 自动推导。

### 生效规则（务必了解）

1. **origin 必须精确匹配**，Playwright 不支持通配。执行器会从环境 `base_url` 与页面地址
   自动推导 origin，通常无需手工填写。
2. **origin 不匹配时证书会被静默丢弃**：不报错，也不发送证书。若访问双向 TLS 站点报握手失败，
   先核对执行器日志里打印的「生效 origin」与页面实际 origin 是否完全一致（含端口）。
3. **格式不受支持 / 口令错误**会在日志中给出明确告警；PKCS#12 或带口令私钥无法解密时，
   本次执行不启用客户端证书，并在结果消息中提示原因。
4. 环境配置中「忽略 HTTPS 证书校验」留空（默认）时，会在证书生效或 stealth 开启时自动忽略
   服务端证书错误；也可显式选择忽略 / 严格。

> 历史说明：早期版本支持在 `config.toml` / 环境变量中配置**节点级**证书
> （`WHARTTEST_ACTUATOR_CLIENT_CERT_*`）。该方式与平台统一管理重复，**已移除**；
> 若配置文件仍保留这些键，启动时会输出一次性迁移提示，但不再生效。

## 文件说明

```
WHartTest_Actuator/
├── main.py              # 主入口，启动执行器
├── models.py            # 消息模型定义
├── websocket_client.py  # WebSocket客户端
├── consumer.py          # 任务消费者
├── executor.py          # Playwright执行引擎
├── client_cert.py       # HTTPS 客户端证书解析（纯函数）
├── browser_installer.py # 浏览器安装检查模块
├── build_exe.py         # 打包脚本
├── actuator.spec        # PyInstaller配置
├── requirements.txt     # 依赖
└── README.md            # 说明文档
```
