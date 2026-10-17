# quote0-glm — 在 Quote/0 电子墨水屏上显示 GLM 余量

把智谱 **GLM Coding Plan** 的用量余量渲染成 296×152 纯黑白像素仪表盘，
通过 Dot 开放平台 Image API 推送到 [Quote/0](https://dot.mindreset.tech/product/quote) 电子墨水屏。

架构与视觉改造自 [ajaxjiang96/quote0-burnout](https://github.com/ajaxjiang96/quote0-burnout)（MIT 协议），
把其中的 Codex/Claude provider 替换为 GLM 用量 provider，单 provider 独占整屏。

![preview](tmp/preview.png)

## 屏幕内容

```
GLM CODING PLAN PRO                          16:40   ← 套餐档位 + 刷新时间
- - - - - - - - - - - - - - - - - - - - - - - - - -
5h  [████████████░░░░░░░░]                    56%   ← 5小时窗口余量 + 进度条
Wk  [██████░░░░░░░░░░░░░░]                    47%   ← 每周窗口余量
MCP [████████████████░░░░]                    93%   ← MCP 月度用量余量
- - - - - - - - - - - - - - - - - - - - - - - - - -
5h 2h13m  Wk 3d4h  MCP 928/1000             WARN   ← 重置倒计时 + MCP 次数 + 状态
```

- 进度条填充的是**余量**（越满越安全），右侧大字为余量百分比
- 状态阈值：余量 ≥30% 为 `OK`，<30% 为 `WARN`，<10% 为 `HOT`
- 拉取失败但本地有上次成功数据时，显示缓存内容并在时间戳后加 `*`
- 老套餐没有每周额度时，`Wk` 行自动省略

## 前置条件（Quote/0 官方 App 操作）

1. 设备已通电、配网， firmware 正常
2. **创建 API Key**：Dot. App → `More` → `API Key` → `Create API Key`（也可在
   [web panel](https://dot.mindreset.tech/panel?tab=api-keys) 创建），密钥只显示一次，注意保存
3. **获取设备序列号**：设备设置页可见（即 `QUOTE0_DEVICE_ID`）
4. **添加 Image API 卡片**：App 的 Content Studio 中，把 `Image API` 内容加入
   设备的播放列表——这是官方 Image API 的硬性前置条件，没有这张卡片推送会 404

## 数据来源（GLM）

使用社区从智谱官方用量页面抓包发现的接口（非公开文档，
[cc-switch #1588](https://github.com/farion1231/cc-switch/issues/1588)，2026-10 已验证可达）：

| 套餐 | 端点 |
|---|---|
| 国内个人版（默认） | `GET https://open.bigmodel.cn/api/monitor/usage/quota/limit` |
| 国际版 z.ai | `GET https://api.z.ai/api/monitor/usage/quota/limit` |
| 团队版 | `GET https://bigmodel.cn/api/monitor/usage/quota/limit?type=2` |

认证：`Authorization: <GLM_API_KEY>`（开放平台
[bigmodel.cn](https://open.bigmodel.cn) 的 API Key，Bearer 前缀可选，脚本会自动兼容）。
团队版另需 `GLM_ORG` / `GLM_PROJECT`（控制台用量页的网络请求里可找到）。

## 安装与配置

```powershell
cd E:\Code\Dot\quote0-glm
pip install -r requirements.txt        # requests + Pillow
Copy-Item config.example.env .env      # 然后编辑 .env 填入三个关键值：
#   QUOTE0_API_KEY   Dot. App 里创建的 dot_app_xxx
#   QUOTE0_DEVICE_ID 设备序列号
#   GLM_API_KEY      智谱开放平台 API Key
```

## 使用

```powershell
# 渲染到本地预览（不推送）—— 先看效果
.\run.ps1 -preview          # 等价于 python quote0_glm.py --preview

# 自检：环境变量 / GLM 接口 / 渲染 / Quote/0 端点连通性
.\run.ps1 -check

# 查看设备上的卡片槽位（fixed / loop），排障用
.\run.ps1 -list-tasks

# 打印解析后的用量 JSON
.\run.ps1 -debug-json

# 单次推送
.\run.ps1

# 前台自循环（每 5 分钟，最低 60s）
.\run.ps1 -interval 5m
```

### Windows 定时任务（推荐）

```powershell
# 注册计划任务：登录后每 30 分钟静默刷新（日志在 tmp\quote0-glm-scheduled.log）
.\register-task.ps1

# 撤销
Unregister-ScheduledTask -TaskName quote0-glm -Confirm:$false
```

### 其他平台

```bash
set -a; source .env; set +a
python3 quote0_glm.py            # 或用 --interval 5m / cron / systemd timer
```

## 部署到 GitHub Actions（不依赖电脑常开）

项目自带 `.github/workflows/refresh.yml`：云端每小时抓一次 GLM 用量并推送到设备，
本机不需要开机。密钥全部放 GitHub Secrets，代码库里没有任何敏感信息
（`.env` 已被 `.gitignore` 排除）。

1. 在 GitHub 新建**私有**仓库（如 `quote0-glm`），把本项目 push 上去
2. 仓库 **Settings → Secrets and variables → Actions → New repository secret**，添加三条：

   | Name | Value |
   |---|---|
   | `QUOTE0_API_KEY` | Dot. App 创建的 `dot_app_...` |
   | `QUOTE0_DEVICE_ID` | 设备序列号 |
   | `GLM_API_KEY` | 智谱开放平台 API Key |

3. **Actions** 标签页确认 `refresh` 工作流已启用，点 **Run workflow** 手动跑一次验证
   （运行详情里可下载 preview.png 查看当次渲染的图）
4. 之后每 15 分钟自动刷新（cron UTC :07/:22/:37/:52）。**公有仓库 Actions
   时长不限量**，频率随便调；若保持私有仓库，注意免费额度 2000 分钟/月
   （每小时一次约 720 分钟，每 30 分钟约 1440 分钟）

安全设计：依赖锁定精确版本（防供应链投毒）、workflow 不打印任何密钥、
job 超时 5 分钟、令牌泄漏可随时在 Dot App / 智谱控制台作废重发。
公有仓库时 Actions 日志公开可见——日志里只有用量百分比，密钥依然受
Secrets 保护不可见。本地 Windows 计划任务可与 Actions 共存
（后推送的覆盖先推送的），也可只留一边。

## 排障

| 现象 | 处理 |
|---|---|
| 推送返回 404 | App Content Studio 里没加 Image API 卡片：删掉旧卡片重新添加，或用 `--list-tasks` 确认槽位后把 key 填进 `QUOTE0_IMAGE_TASK_KEY` |
| 屏幕显示 `401 unauthorized` | `GLM_API_KEY` 无效或过期，去开放平台重新生成 |
| 屏幕时间戳带 `*` | GLM 接口暂时拉不到（断网/限流），正在显示上次成功的数据 |
| 文字发虚 | 确认推送走的是 Image API（默认），`ditherType=NONE` 已在代码里固定 |
| 频率限制 | 官方 Image API 限每秒 10 次；本脚本 30 分钟一次远低于上限 |

## 文件结构

```
quote0_glm.py            主程序：抓取 → 快照(缓存兜底) → 渲染 → 推送
glm.py                   GLM provider：用量接口解析（fetch → snapshot → text）
render.py                296×152 纯黑白渲染器（像素字体 + 点阵进度条）
assets/fonts/            像素字体（PixelOperator 16 / Minecraftia 8 / VCR OSD 21）
config.example.env       配置模板
run.ps1 / register-task.ps1 / run-scheduled*.ps1/.vbs   Windows 运行与定时任务
```

## 致谢与许可

- [ajaxjiang96/quote0-burnout](https://github.com/ajaxjiang96/quote0-burnout)（MIT）— 架构、渲染审美与字体
- [Dot / MindReset](https://dot.mindreset.tech) — Quote/0 开放平台
- GLM 用量端点发现：[cc-switch issue #1588](https://github.com/farion1231/cc-switch/issues/1588) 的社区贡献者
