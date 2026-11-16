# NfoCheck 1.2.5

MoviePilot V3 插件，宿主接口基线 3.2.5。

按多套规则巡检 NFO 和图片，可选择性修复，支持备份、断点续跑和 Emby 定向刷新。可选联动 [元数据翻译](https://github.com/JKRaks/mpp-nfotrans)。

## 安装

在 MoviePilot 插件市场添加仓库 `https://github.com/JKRaks/mpp-nfochecker`，然后安装 NfoCheck。仓库已包含对应版本的完整前端产物。

翻译服务的 API Key 需要自行配置。仓库不包含个人设置或密钥。

## 构建

环境：Node 26.13.0，npm 11.20.0。

```bash
cd frontend
npm ci
npm run build
cd ..
python3 scripts/package.py
```

构建只生成本项目的插件包。

## 验证状态

- 已完成：类型检查、前端构建和安装包校验。
- 未完成：1.2.5 的 MoviePilot 安装验证及功能测试。
