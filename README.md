# NodeSeek 自动签到评论加鸡腿脚本

这是一个用于 NodeSeek 论坛的自动化脚本，包含签到、评论和加鸡腿功能。使用 Selenium 和 undetected-chromedriver 实现自动化操作。

强烈建议修改随机词。否则容易被举报被禁言。有能力的可以fork后自己定义改。

## 功能特点

- 自动签到（点击签到图标）
- 自动点击"试试手气"或"鸡腿 x 5"按钮（可配置）
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
- 真实浏览器启动测试：`python -m unittest discover -s tests -p 'smoke_browser_startup.py' -v`

真实浏览器测试需要已安装 Chrome/Chromium，并可能下载对应的 ChromeDriver。它只打开本地 `data:` 页面、核对浏览器和驱动的主版本号，然后关闭浏览器，不访问 NodeSeek、不登录、不签到。独立的 `Browser startup tests` 工作流也会运行这两项检查，不使用仓库 Secrets。

## GitHub Actions 自动运行

1. Fork 本仓库
2. 在仓库的 Settings -> Secrets 中添加 `NS_COOKIE`
3. 可选：添加 `NS_RANDOM` 设置是否随机选择奖励
4. Actions 会在每天 UTC 16:00（北京时间 00:00）自动运行


## 注意事项

- 请确保 Cookie 有效且具有足够的权限
- 评论内容较为简单，建议根据需要修改 `randomInputStr` 列表
- 加鸡腿功能仅对 7 天内的帖子有效


