# UESTC 电费监控

电子科技大学「云中成电」宿舍电费监控：用统一身份认证的学号与密码自动换取门户会话，定时查询剩余电费，低于阈值时通过 Server酱（或 QQ 邮件）提醒，避免欠费自动断电。

不依赖浏览器 Cookie、不依赖系统计划任务，程序自己倒计时。

## 它怎么工作

1. 学号 + 密码 → 统一身份认证（CAS）登录 → 门户会下发会话 Cookie（`cookie_vjuid_portal_login`）
2. 会话 Cookie 加密保存在本地，之后的查询直接复用，**不需要每次登录**
3. `GET https://online.uestc.edu.cn/site/bedroom` → 剩余金额 `syje` / 剩余电量 `sydl`
4. 余额低于阈值 → 推送到启用的渠道（默认 Server酱）

首次登录如果学校要求二次认证，程序会发一条短信验证码；勾选「信任此浏览器」并完成一次之后，本地保存的会话会长期复用。

## 最少只要三项配置

界面上真正必填的只有：

| 配置 | 说明 |
| --- | --- |
| 学号 | 统一身份认证账号，如 `2023000000000` |
| 密码 | 统一身份认证密码（本地 DPAPI 加密保存，Windows） |
| Server酱 SendKey | `SCT...` 或 `sctp...t` 均可，自动选择接口 |

其余全部有默认值或可留空：房间号/电表号从接口返回里读，阈值默认 10 元，间隔默认 30 分钟，重复提醒默认 12 小时。

> QQ 邮件是可选的第二个渠道：选类型 `email`，填发件邮箱与 SMTP 授权码（QQ 邮箱 → 设置 → 账号 → 生成授权码）。收件人留空即发给自己。

## 使用

发行版双击运行（Windows 为 `uestc-energy-windows.exe`，Linux 为 `uestc-energy-linux`）：

- 首次启动会在**程序所在目录**生成 `config.json`（配置）与 `state.json`（会话与上次结果）
- 在面板里添加用户、添加渠道（渠道可设标签，用户可指定只收某些标签的消息）
- 点「开始监控」，窗口底部显示下次检查倒计时
- 首次登录点「短信认证」，按提示填一次验证码

### 免短信（可选）

如果不想在换机/会话过期后再收短信，可从浏览器复制一次可信浏览器指纹：

1. 用浏览器登录一次「云中成电」
2. F12 → Application → Cookies → `https://idas.uestc.edu.cn` → 复制 `MULTIFACTOR_BROWSER_FINGERPRINT` 的值（32 位十六进制）
3. 填进面板用户编辑里的「浏览器指纹（可选，免短信用）」

填了它，登录会直接放行，不再要求短信。

## 命令行

```bash
python main.py check        # 查一次（用已保存的会话）
python main.py login        # 交互式登录，保存会话（需要时输入验证码）
python main.py run          # 持续轮询，按配置的间隔
python main.py notify       # 给所有启用渠道发一条自检消息
```

打包后的可执行文件同样支持这些子命令，例如 `uestc-energy-linux run`。

## 从源码运行 / 编译

```bash
python -m pip install -r requirements.txt
python main.py
```

打包单文件可执行程序（Windows 产出 `.exe`，Linux 产出无扩展名的可执行文件）：

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --onefile --console --name uestc-energy --collect-submodules uestc_energy main.py
```

产物在 `dist/`。

说明：单文件（`--onefile`）首次运行会把自己解压到临时目录，个别杀毒软件或受限环境会拦截这次解压（报 `failed to open target file`／`Permission denied`）。遇到时改用目录模式即可，功能完全一样：

```bash
python -m PyInstaller --noconfirm --onedir --console --name uestc-energy --collect-submodules uestc_energy main.py
```

仓库自带 GitHub Actions（`.github/workflows/build.yml`），推送 `v*` 标签会在 Windows 与 Linux 上各构建一份、重命名为 `uestc-energy-windows.exe` 与 `uestc-energy-linux` 并附到 Release。

## 配置项

`config.json` 顶层：

| 键 | 默认 | 说明 |
| --- | --- | --- |
| `intervalMinutes` | 30 | 检查间隔（分钟） |
| `thresholdYuan` | 10 | 全局告警阈值（元） |
| `repeatNotifyHours` | 12 | 持续低于阈值时的重复提醒间隔 |
| `channelTags` | 空 | 全局默认接收渠道标签 |
| `users` | 空 | 用户列表，各自可设 `thresholdYuan` / `channelTags` / `fingerprint` |
| `channels` | Server酱 + QQ 邮件 | `tag` 是渠道标签，`type` 取 `serverchan` 或 `email` |

机密字段（密码、SendKey、授权码）在 Windows 上用 DPAPI 加密（文件中形如 `dpapi:...`），在其它平台写入后把权限收紧到 0600。

## 已知限制

- 学校改版登录页或电费接口时，需要跟着改 `uestc_energy/auth.py` / `api.py`
- 会话 Cookie 会过期；过期后程序自动重登，若那时要求短信，面板里会显示「需要短信认证」
- `/site/bedroom` 偶尔返回一种「降级响应」（给一个带签名的代理地址），程序会自动重试并兼容该形态
- 程序只做查询与提醒，不代充值

## 免责

仅用于查询自己的宿舍电费。请勿用于批量扫描或他人账号。
