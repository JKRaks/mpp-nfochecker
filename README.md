# NfoCheck 1.2.4

MoviePilot V3 插件，宿主接口基线 3.2.5。

按多套规则巡检 NFO 和图片，选择性修复、可配置备份、断点续跑及 Emby 定向刷新。可选联动 [元数据翻译](https://github.com/JKRaks/mpp-nfotrans)。

## 安装

在 MoviePilot 插件市场添加仓库 `https://github.com/JKRaks/mpp-nfochecker`，安装 NfoCheck。仓库包含对应版本完整前端产物。翻译服务需要自行配置 API Key；不上传个人设置或密钥。

## 构建

Node 26.13.0 / npm 11.20.0：

```bash
cd frontend
npm ci
npm run build
cd ..
python3 scripts/package.py
```

构建仅生成本项目的插件。前端类型检查及构建已完成，本版本功能测试尚未执行，已通过本地 MoviePilot 安装及设置接口确认。

[验收交接](TRANSLATION_TESTING.md)描述两个插件的联动场景；另一项目的文件请在对应仓库查阅。未附带真实媒体、运行数据库、私密环境和历史验收截图。

## 本版界面更新

详情使用弹窗，提供中文字段分组与原始内容切换；两个插件采用统一全宽标题栏及关闭按钮。新增只读 NFO 备份详情。

类型检查、前端构建和本地安装已完成，功能测试未执行。详见 [界面复验交接](UI_DETAILS_TESTING.md)。
