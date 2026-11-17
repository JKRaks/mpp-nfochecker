# NfoCheck 1.2.9

MoviePilot V3 插件，宿主接口基线 3.2.5。

按多套规则巡检 NFO 和图片，可选择性修复，支持备份、断点续跑和 Emby 定向刷新。可选联动 [元数据翻译](https://github.com/JKRaks/mpp-nfotrans)。

## 安装

在 MoviePilot 插件市场添加仓库 `https://github.com/JKRaks/mpp-nfochecker`，然后安装 NfoCheck。仓库已包含对应版本的完整前端产物。

翻译服务的 API Key 需要自行配置。仓库不包含个人设置或密钥。

安装包可从 [Releases](https://github.com/JKRaks/mpp-nfochecker/releases) 下载；最新构建位于 [Actions](https://github.com/JKRaks/mpp-nfochecker/actions/workflows/package.yml) 成功运行记录的 Artifacts 中，保留 30 天。下载内容包含插件 ZIP 和 SHA256 校验文件。

## 页面与队列管理

- 规则集及规则以摘要展示，展开当前规则编辑。可从 NFO、图片模板创建规则集，再设置检查目录并试运行。
- 常用 NFO 条件集中勾选，高级条件、翻译策略和自定义字段仍可编辑。配置修改统一保存，有未保存修改时运行按钮会提示先保存。
- 设置按执行策略、备份、Emby 联动、通知和备份恢复分组。
- 待同步支持单条或选择本页任务后批量移出。移出仅清理当前队列，保留媒体文件、备份、同步回执和历史记录；后续运行再次触发同步时可重新入队。任务运行期间不可移出。
