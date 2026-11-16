# NfoCheck 1.2.4

MoviePilot V3 插件，宿主接口基线 3.2.5。

按多套规则巡检 NFO 和图片，选择性修复、可配置备份、断点续跑及 Emby 定向刷新。可选联动 [元数据翻译](https://github.com/JKRaks/mpp-nfotrans)。

## 安装

在 MoviePilot 插件市场添加仓库 `https://github.com/JKRaks/mpp-nfochecker`，安装 NfoCheck。仓库包含对应版本完整前端产物。翻译服务需要自行配置 API Key；不上传个人设置或密钥。

## 使用

1. 在设置页添加规则集，选择巡检目录、媒体层级和排除项，设置 NFO 字段及图片检查条件。
2. 先试运行，查看命中原因与处理范围；确认后正式执行所选的 NFO、图片或翻译动作。
3. 默认每批处理 100 个可修复对象。启用自动续跑后，默认最多执行 3 批；也可在运行记录中继续剩余任务。
4. 在结果页查看处理详情、失败原因和待同步条目。详情支持格式化视图及原始 XML / JSON 切换。
5. 按需开启 NFO 与图片备份。NFO 备份支持只读预览，恢复操作使用独立入口。

翻译需要安装 [MetadataTranslate](https://github.com/JKRaks/mpp-nfotrans) 并配置翻译服务。`translate` 处理已有 NFO 的所选文字字段，`nfo_translate` 先生成 NFO 再翻译。配置示例见 [examples/nfocheck-translation.json](examples/nfocheck-translation.json)。

## 开发与验证

Python 3.10+；Node 26.13.0 / npm 11.20.0（项目声明版本）。

```bash
cd frontend
npm ci
npm run build
cd ..
python3 scripts/package.py
```

`npm run build` 包含类型检查，生成的前端文件位于 `plugins.v3/nfocheck/dist`。打包脚本检查前端版本与插件清单，输出 `artifacts/NfoCheck-1.2.4.zip` 及 SHA-256 校验文件。

后端已有巡检与 Emby 回归用例，可在安装测试依赖后执行：

```bash
python3 -m pip install pytest Pillow requests "pydantic>=2"
python3 -m pytest -q tests
```

### 代码格式

Python 使用 Black 与 isort，配置在 `pyproject.toml`；Vue、TypeScript、JSON 和 HTML 使用根目录 `.prettierrc.json`。统一行宽为 100。

```bash
python3 -m pip install black isort
python3 -m isort plugins.v3/nfocheck scripts tests
python3 -m black plugins.v3/nfocheck scripts tests
npx prettier --write "frontend/src/**/*.{vue,ts,json}" frontend/vite.config.ts frontend/index.html frontend/tsconfig.json package.v3.json "examples/*.json"
```

`frontend/node_modules`、Python 缓存和 `artifacts` 不提交。前端源码调整后应重新构建并提交对应产物。

## 本版界面更新

详情使用弹窗，提供中文字段分组与原始内容切换；两个插件采用统一全宽标题栏及关闭按钮。新增只读 NFO 备份详情。
