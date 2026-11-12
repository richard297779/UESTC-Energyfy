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

## 三分钟上手

1. 从 [Releases](https://github.com/richard297779/UESTC-Energyfy/releases) 下载对应平台的文件（Windows：`uestc-energy-windows.exe`；Linux：`uestc-energy-linux`），放到一个自己的文件夹里
2. 双击运行。第一次会在**同目录**生成 `config.json` 与 `state.json`，并弹出面板
3. 面板里点「添加用户」，只填三项：备注名（随便写，如"宿舍 A-101"）、学号、密码 → 确定
4. 点「添加渠道」，类型选 `serverchan`，标签保持 `serverchan`，把 Server酱 SendKey 粘进去 → 确定
5. 点「保存配置」→「立即检查」。正常会写出一行 `[时间] [学号] 余额 xx 元，剩余 xx 度，阈值 xx`
6. 点「开始监控」，窗口底部出现"下次检查 xx:xx"就说明在倒计时了，可以最小化挂后台

配置文件、会话缓存、日志都在程序同目录，换机器时整个文件夹一起拷走即可。

### 打不开 / 双击没反应怎么办

单文件 exe 每次启动要先把内置的 Python 运行时解压到临时目录，杀毒软件（Defender、卡巴斯基等）常把这一步拦掉，表现为"双击没反应"或窗口一闪而过。

两条对策：

1. **改用文件夹版**：Release 里的 `uestc-energy-windows-onedir.zip` / `uestc-energy-linux-onedir.zip`，解压后运行里面的 `uestc-energy.exe`（Windows）或 `uestc-energy`（Linux）。不需要解压到临时目录，杀软拦截概率低得多，启动也更快。
2. **看启动日志**：程序启动时会在同目录写 `startup.log`，并在导入图形界面或初始化窗口失败时弹出「uestc-energy 启动失败」对话框，同时把完整调用栈写进这个文件。把 `startup.log` 的最后一段发出来即可定位。

如果连日志都没有生成，说明进程在 Python 启动之前就被拦住了（杀软/组策略/未授权目录），换到文件夹版或给该目录加白名单。

### 第一次会要短信验证码

学校对"没见过的浏览器"要求二次认证。程序会弹框问验证码：

- 点「短信认证」→ 手机上会收到 6 位码（学校发到统一身份认证里登记的号码）→ 填进去 → 勾选信任即可
- 验证通过后会话加密存本地，之后正常情况不再打扰你

### 收不到短信验证码怎么办

学校这条短信本身偶尔不发或延迟很久（本机实测出现过多次收不到）。两条替代路径：

1. **用浏览器指纹跳过短信（推荐，长期有效）**：浏览器登录一次「云中成电」→ F12 → Application（应用）→ Cookies → `https://idas.uestc.edu.cn` → 找到 `MULTIFACTOR_BROWSER_FINGERPRINT`，复制它的值（32 位十六进制）→ 面板里编辑该用户，粘贴到「浏览器指纹（可选，免短信用）」→ 保存。有了它登录直接放行，不再发短信。
2. **直接复用已有会话**：如果这台机器之前的 `state.json` 里还有有效会话（例如从旧目录拷过来），程序不会重新登录，也就不会要验证码，直到会话过期为止。

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
python main.py version      # 查看程序版本
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

仓库自带 GitHub Actions（`.github/workflows/build.yml`），推送 `v*` 标签会在 Windows 与 Linux 上各构建一份，并附到 Release。Release 说明会读取相邻版本标签之间的 Conventional Commit 消息，按新功能、问题修复、文档、构建与发布等类别自动生成。

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
- 门户住宿数据偶尔短时缺失，程序会在单次检查中自动重试 90 秒；若学校首页也没有电费卡片，仍需等待学校侧数据恢复
- 程序只做查询与提醒，不代充值

## 免责

仅用于查询自己的宿舍电费。请勿用于批量扫描或他人账号。

## 许可证

本项目采用 [MIT License](LICENSE) 开源。
