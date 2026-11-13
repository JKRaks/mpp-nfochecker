# NfoCheck 元数据巡检

MoviePilot V3 插件（宿主接口基线 3.2.5，插件版本 1.2.0）。

按自定义规则巡检 NFO 与图片，只对命中项做选择性补刮，支持可配置备份、断点续跑和 Emby 定向刷新，可选联动[元数据翻译插件](https://github.com/JKRaks/mpp-nfotrans)。

## 功能

| 能力 | 说明 |
| --- | --- |
| 多套规则 | 按目录、媒体类型、排除项组织规则集；条件支持字段缺失/为空/长度/正则/身份缺失/冲突以及语言条件 |
| 精确区分层级 | 电影、整剧、季、单集分别判定；路径与 NFO 冲突时转人工，不误判、不误写 |
| 选择性修复 | 每条规则可只报告、只补 NFO、只补指定图片，或同时处理；不触碰未选中的资产 |
| 备份与恢复 | NFO 与图片备份可分别开关，按天数与版本数清理，可从历史备份恢复 |
| 断点续跑 | 按批次限额执行，支持自动续跑；停止、重启或中断后从上次进度继续 |
| 失败分类 | 来源无内容、候选不合格、网络、IO、文件冲突、内部错误分别计数与冷却，不混为一谈 |
| Emby 定向刷新 | 只刷新实际改动的条目，提交后先复查再补发，逐服务记录回执 |
| 可观测性 | 运行摘要、条目分页、失败详情、待同步列表与持久化状态 |

## 安装

1. 在 MoviePilot 插件市场添加仓库 `https://github.com/JKRaks/mpp-nfochecker`。
2. 安装 **NfoCheck**，仓库内已包含对应版本的前端产物。
3. 打开插件设置，添加至少一个规则集与巡检目录后启用。

翻译联动需要另外安装 [MetadataTranslate](https://github.com/JKRaks/mpp-nfotrans) 并自行配置服务 API Key。本插件不上传个人设置或密钥。

## 使用流程

1. **配置规则**：选择目录与媒体类型，设置排除目录/排除正则/是否跳过特别篇。默认规则集检查 NFO 基础完整性、主图、徽标、背景图和单集主图。
2. **试运行**：只做检查与报告，不写文件、不刷新 Emby，用来确认命中范围。
3. **正式运行**：按 `batch_limit`（默认 100）处理；可在设置里开启自动续跑并限制本次最大批数（默认 3）。
4. **查看结果**：运行记录按条目分页展示命中原因、动作、失败分类与剩余资产；需要时继续剩余任务或对单条重试。
5. **备份与恢复**：需要回退时从备份记录恢复，恢复后可选立即刷新 Emby。

### 翻译规则（可选）

| 动作 | 行为 |
| --- | --- |
| `translate` | 只翻译所选字段，要求已有可用 NFO |
| `nfo_translate` | 先用官方来源重建 NFO，再翻译所选字段 |

语言条件（`language_missing` / `language_mismatch` / `language_unknown`）仅支持标题、简介、摘要、宣传语四个字段，且必须包含在所选翻译字段中。示例配置见 [examples/nfocheck-translation.json](examples/nfocheck-translation.json)。

## 开发

环境要求：Python 3.10+（打包脚本仅用标准库）；Node 26.13.0、npm 11.20.0（见 `frontend/package.json` 的 `engines`）。

```powershell
# 前端：安装依赖、类型检查、生产构建
cd frontend
npm ci
npm run typecheck   # vue-tsc --noEmit
npm run build       # 类型检查 + Vite 生产构建
cd ..

# 打包
python scripts/package.py
```

`node_modules`、`artifacts` 均不入库，需要时重新生成。

### 代码风格

- Python 使用 [black](https://github.com/psf/black)，配置见根目录 `pyproject.toml`（行宽 100）；导入顺序用 `isort --profile black`。
- 前端与 JSON、HTML 使用 [Prettier](https://prettier.io/)，配置见根目录 `.prettierrc.json`（无分号、单引号、行宽 100、LF）。

```powershell
python -m black plugins.v3/nfocheck scripts
python -m isort --profile black --line-length 100 plugins.v3/nfocheck scripts

cd frontend
npx prettier --write "src/**/*.{vue,ts}" vite.config.ts index.html package.json tsconfig.json
cd ..
npx prettier --write package.v3.json examples/*.json
```

- 前端产物输出到 `plugins.v3/nfocheck/dist`；`build-meta.json` 需与 `package.v3.json` 的插件名和版本一致，否则打包脚本拒绝执行。
- 安装包输出到 `artifacts/NfoCheck-<版本>.zip` 及同名 `.sha256`；相同输入重复打包得到相同字节。

### 目录结构

```text
plugins.v3/nfocheck/   插件后端（core/engine/emby/store/state/translation 等）
frontend/src/          Vue 配置页与运行页
scripts/package.py     确定性打包脚本
examples/              配置示例
pyproject.toml         Python 格式化配置（black）
.prettierrc.json       前端与 JSON 格式化配置（Prettier）
```

## 说明

- 仅读写媒体旁挂文件（NFO 与图片），不读取视频正文，不改写 STRM。
- Emby 交互只做查询与刷新，不上传图片、不替换全部图片、不解锁已锁定的元数据。
- 本次发布未附带真实媒体、运行数据库、私密环境或历史验收截图。
