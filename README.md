# NodeSeek 自动签到评论加鸡腿脚本

这是一个用于 NodeSeek 论坛的自动化脚本，包含签到、评论和加鸡腿功能。使用 Selenium 和 undetected-chromedriver 实现自动化操作。

强烈建议修改随机词。否则容易被举报被禁言。有能力的可以fork后自己定义改。

## 功能特点

- 自动签到（在浏览器会话中提交签到接口，并校验服务端结果）
- 固定或随机鸡腿奖励（可配置）
- 随机选择帖子进行评论
- 自动给帖子加鸡腿（7天内的帖子）
- 随机评论内容（"bd"、"绑定"、"帮顶"）
- 支持 GitHub Actions 自动运行
- 支持无头模式（可配置）

## 环境变量配置

- `NS_COOKIE`: NodeSeek 的 Cookie（必需）
- `NS_RANDOM`: 是否随机选择奖励，true/false（可选）
- `HEADLESS`: 是否使用无头模式，true/false（可选，默认 true）

## 本地运行

1. 克隆仓库
2. 安装依赖：`pip install -r requirements.txt`
3. 设置环境变量（可使用 .env 文件）
4. 运行脚本：`python nodeseek_daily.py`

## 浏览器启动测试

脚本会选择一个可用的 Chrome/Chromium 可执行文件，读取该文件的版本，并将路径和主版本号一起传给驱动，避免系统安装多个浏览器时版本不匹配。

安装依赖后，可执行以下测试，无需配置 Cookie：

- 回归测试（使用模拟浏览器）：`python -m unittest discover -s tests -p 'test_*.py' -v`
- 真实浏览器启动测试：`python -m unittest discover -s tests -p 'smoke_*.py' -v`

真实浏览器测试需要已安装 Chrome/Chromium，并可能下载对应的 ChromeDriver。测试只打开本地 `data:` 页面和本机模拟签到接口，验证浏览器/驱动版本、浏览器 Cookie 携带、随机奖励参数、服务端成功/已签到/失败/重定向处理。不访问 NodeSeek，不使用真实账号或仓库 Secrets。独立的 `Browser startup tests` 工作流也会运行这些检查；测试通过不代表真实账号已签到。

## GitHub Actions 自动运行

1. Fork 本仓库
2. 在仓库的 Settings -> Secrets 中添加 `NS_COOKIE`
3. 可选：添加 `NS_RANDOM` 设置是否随机选择奖励
4. Actions 配置为每天 UTC 03:10（北京时间 11:10）触发，随后随机延迟 0–40 分钟；GitHub 调度本身还可能延后


## 注意事项

- 请确保 Cookie 有效且具有足够的权限
- 评论内容较为简单，建议根据需要修改 `randomInputStr` 列表
- 加鸡腿功能仅对 7 天内的帖子有效



## 签到结果与排错

- 仅服务端 JSON 明确返回 `success: true`，或明确返回“今天已完成签到，请勿重复操作”，才以退出码 0 结束
- 找不到按钮、页面打开、浏览器启动、未知响应均不算签到成功；未确认结果退出码为 1，Actions 显示失败
- `unauthenticated`：登录失效或跳转登录页，需在 GitHub Secrets 更新 `NS_COOKIE`
- `challenge`：检测到验证页面后，全程最多被动等待 8 秒复查一次；若仍存在则失败停止，不点击或自动处理验证码
- `http_error` / `request_failed`：请求被拒绝、限流、重定向或网络异常；请检查该次运行日志与站点状态
- `rejected` / `invalid_response`：服务端响应不符合已知成功契约；不可视为已签到
- 日志只输出安全诊断与确认结果，不输出 Cookie、原始页面、账户详情或接口响应正文

脚本在已有浏览器会话中请求 `POST /api/attendance?random=true|false`，避免依赖按钮文字的空格或嵌套结构。接口与结果字段参考 [公开签到脚本](https://github.com/24kcsplus/NodeSeek-Signin/blob/main/signin.sh)及 [NodeSeek 站内发布的浏览器签到实现](https://www.nodeseek.com/post-548000-1)。这些来源不能替代真实账号的运行验证。
