# MetadataTranslate 1.0.0 / NfoCheck 1.2.0 测试交接

交付日期：2026-11-13。**本轮仅实现源码和验收材料，以下测试、类型检查、构建、打包和安装均未执行。** 不执行压力测试。既有 1.1.0 报告描述旧版本，不能作为本版通过证据。

## 1. 交付范围与验收记录

本版增加独立翻译插件、五类服务适配、官方 NFO 候选增强、NfoCheck 语言条件与逐字段续跑、管理页面及双插件打包。没有配置真实 API 密钥，没有请求真实翻译服务，没有写入真实媒体或刷新真实 Emby。

验收人员为每个编号记录：通过 / 失败 / 未执行、环境、复现命令、输入夹具、请求次数、字段前后值、证据路径。参数化用例数与本文场景数分别统计。失败项不能被其他通过项抵消。先完成本地夹具与构建，再在独立 MoviePilot / Emby 实例验收；付费服务由验收人员使用自己的测试额度明确执行。

## 2. 环境和构建入口

宿主接口基线 MoviePilot 3.2.5；Python 3.10+；Node **26.13.0**、npm **11.20.0**。后端依赖见两套插件的 requirements.txt；本版增加 zhconv。安装包不包含开发环境的凭据或数据库。

以下命令留给验收人员，本轮未运行：

```bash
python3 -m venv /tmp/nfocheck-translation-venv
/tmp/nfocheck-translation-venv/bin/pip install -e '.[test]'
cd frontend
npm ci
npm run build
cd ..
python3 scripts/package.py --plugin all
```

`npm run build` 先对两套 Vue 源码做类型检查，再分别构建 NfoCheck 和 MetadataTranslate；可用 `build:nfocheck` / `build:translate` 单独构建。前端包版本 1.2.0，两个插件的发布版本来自 `package.v3.json`。`build-meta.json` 必须同时包含正确的 `plugin` 与 `version`。

预期产物：`artifacts/NfoCheck-1.2.0.zip`、`artifacts/MetadataTranslate-1.0.0.zip` 及各自 `.sha256`。打包命令拒绝缺失、旧版本或错误插件的 dist。现存旧 ZIP 和旧 dist 不代表本次交付。

## 3. 本地模拟接口

夹具为 `tests/translation/mock_server.py`、`fixture_support.py` 和 `fixtures/movie.nfo`。它们是交给验收方的模拟基础设施，不是本轮已运行的自动测试。

终端一：

```bash
/tmp/nfocheck-translation-venv/bin/python tests/translation/mock_server.py --port 18765
```

终端二可用以下脚本检查一次候选，替换 `provider_name` 和 `scenario` 扩展场景：

```python
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
sys.path.insert(0, str(Path('tests/translation').resolve()))
from fixture_support import load_core, FakeSource, provider_factory

core = load_core()  # 不执行依赖 MoviePilot 的插件 __init__.py
provider_name = 'siliconflow_hunyuan'
scenario = 'success'
config = core['config'].Config(enabled=True, active_provider=provider_name)
config.policies[0].fields = ['title', 'plot', 'outline', 'tagline']
if not config.provider_configs[provider_name].model:
    config.provider_configs[provider_name].model = 'fixture-model'
if not config.provider_configs[provider_name].endpoint:
    config.provider_configs[provider_name].endpoint = 'http://127.0.0.1:18765'
with TemporaryDirectory() as directory:
    storage = core['storage'].Storage(directory)
    storage.save_secrets({provider_name: 'fixture-token'})
    service = core['service'].TranslationService(config, storage, FakeSource(),
        provider_factory(core, scenario=scenario))
    try:
        result = service.prepare_nfo(
            {'kind': 'movie', 'tmdb_id': 42, 'title': 'A Journey'},
            Path('tests/translation/fixtures/movie.nfo').read_bytes(),
            fields=['plot', 'tagline'])
        print(result)
    finally:
        service.close()
```

`provider_factory` 强制将所有实际传输重定向到 loopback，包括 DeepL 固定的生产地址和 Gemini 原生路径。它不修改生产适配器配置、不向供应商转发流量。只接受假密钥 `fixture-token`。不得在这套模拟夹具中放入真实凭据。

| provider_name | 要检查的请求 |
| --- | --- |
| deepl | DeepL-Auth-Key；text 数组；target_lang/source_lang；无 messages |
| siliconflow_hunyuan | 单段 user 消息；无 response_format；每个不同原文单独请求 |
| openrouter | JSON ID 映射；指定 model；allow_fallbacks=false；无备用 models |
| gemini_native | contents/systemInstruction/generationConfig；无 messages；密钥在头中 |
| chat_completions | Bearer；messages；选择的 JSON 响应模式 |

场景：`success`、`partial`、`missing`、`empty`、`unknown`、`malformed`、`truncated`、`blocked`、`http-401`、`http-402`、`http-403`、`http-429`、`http-456`、`http-500`、`delay`。部分场景仅适用于具有相应响应结构的服务：例如 DeepL 没有 JSON 对象未知键或 finish_reason；Hunyuan 的 partial 表现为第二段限流。

`GET http://127.0.0.1:18765/calls` 返回请求体和计数；不返回认证头。`DELETE /calls` 清空夹具记录。`delay` 延迟 7 秒，将配置 timeout 设为 5 秒检查超时。用受控时钟验证重试时间，不需要长时间等待或压力测试。

## 4. 独立插件与语言判定

| 编号 | 输入 / 操作 | 必须观察到 |
| --- | --- | --- |
| T01 | 首次安装；只安装 NfoCheck / 只安装翻译插件 | 默认关闭；两个插件可独立加载；缺少翻译插件不影响普通图片规则 |
| T02 | 五类服务配置切换后重新打开设置 | 各服务参数独立保留；只有一个全局当前服务；策略中没有供应商字段 |
| T03 | 保存、留空、删除密钥；读取配置 / 历史 / 错误 | 留空保留，删除需保存；secret 文件 0600；返回值及日志无完整密钥 |
| T04 | 多策略、默认策略、删除默认策略、重复 ID、无效字段 | 合法配置保留；非法配置返回明确错误；默认策略始终存在 |
| T05 | 目标 zh-CN 的 translations 有正式 plot，详情回退为英文 | 使用正式译文；不调用翻译供应商；plot 和 outline 可共用同一 overview |
| T06 | 没有简体、存在繁体，转换开 / 关 | 开启时本地转换；关闭时依策略继续备用语言或调用当前服务 |
| T07 | 繁体无值、英文有值；只有原语言有值 | 按配置顺序选非空原文；保留实际来源语言；不借用其他媒体剧情 |
| T08 | 所有语言该字段均为空 | 标记 no_source_text；不发翻译请求；NfoCheck 字段待办默认 7 天后复查 |
| T09 | TMDB 网络错误 / 缺 translations 结构 / 错误实体 ID | source_unavailable 或 identity_unknown；不得记成无原文或成功 |
| T10 | source_only 策略，只有英文原文 | 不调用云端服务；保留未完成字段，说明缺少可直接采用的内容 |
| T11 | 本地内容与来源完全对应 / 本地内容无法对应 | 前者按语言策略补齐；后者 language_unknown 并保留本地文字 |
| T12 | 已翻译字段原样重试 / 手工改写后重试 | 原样不重复写；手改输出哈希不符，标记 protected |
| T13 | 来源补上正式译文；prefer_official 开 / 关 | 开启时替换未修改的机器译文；关闭时保留；手改内容仍受保护 |
| T14 | 空白、重复文字节点、DOCTYPE、实体声明、节点内含子元素 | 空白可补齐；不确定结构不被覆盖；实体声明拒绝 |
| T15 | 字段包含 &、引号、换行、注释；其他字段含 CDATA | 修改字段正确 XML 转义；未选节点的内容和自定义数据保留 |
| T16 | title 为 Episode 1 / 第 1 话；选择原始标题、人名、ID | 占位标题不作为翻译原文；白名单外字段不可选、不可写 |
| T17 | 季 / 单集选择 tagline | 明确 not_applicable，不反复形成无法完成的翻译待办 |
| T18 | TMDB 电影、整剧、普通季、普通单集 | 来源对象 ID、类型、季集编号正确；各层级独立查询 |
| T19 | 分集组重排；本地 E01 对应原始 S02E05 | 查询原始 S02E05 translations；写回仍保留本地编号 |
| T20 | 跨季分组 / 不完整原始季映射 / 分组缺原始 ID | 季译文转人工；不得使用错误季摘要或仅凭显示编号猜测 |

## 5. 供应商契约、缓存和调用记录

| 编号 | 输入 / 操作 | 必须观察到 |
| --- | --- | --- |
| V01 | 五种服务逐一 success | 请求结构与第 3 节一致；每个请求 ID 对应正确原文；仅当前服务收到请求 |
| V02 | DeepL Free / Pro；来源语言混合；中文、英语、法语目标 | 地址和认证方案正确；同语言分组；语言码映射正确；有序结果不串字段 |
| V03 | DeepL 超过 50 段 / 128 KiB；文本超配置上限 | 按服务限制分批；单条过大明确失败，不截断、不发送超大请求 |
| V04 | Hunyuan 两段不同原文；两字段同原文 | 前者两次纯文本请求，后者合并一次；不使用 JSON 系统提示词 |
| V05 | OpenRouter 三种响应模式；模型不支持 schema | 正确带格式参数；unsupported 不换模型、不降级重发、不换服务 |
| V06 | Gemini v1 / v1beta；带 / 不带 models/ 前缀 | 原生 generateContent 路径正确，密钥不在查询串，解析 parts 正文并排除 thought |
| V07 | 返回多余字段、缺字段、空值、坏 JSON | 多余字段 / 坏结构拒绝；缺失或空值仅相关字段失败；不把响应正文直接写 NFO |
| V08 | length / MAX_TOKENS、拒答 / 内容拦截 | 分别报告 truncated / blocked，保留本地字段 |
| V09 | 401/403、402/456、429 + Retry-After、5xx | 鉴权 / 额度 / 限流 / 服务错误分类；429 保留复查时间；不透传服务错误正文 |
| V10 | delay、连接失败；第二段超时或限流 | 超时 / 网络错误明确；前面成功的段仍能作为部分候选；不会重复调用成功字段 |
| V11 | 连续相同媒体与原文请求 | 命中译文缓存；plot/outline 去重；改变模型、语言、原文、身份或实际上下文后失效 |
| V12 | 同一原文同时请求；并发限制 1 / 2 | 等待后共享成功缓存；供应商活跃请求不超过配置值；停止等待不会发新请求 |
| V13 | 不同服务缓存；切回原服务；明确 force | 无跨服务缓存混用；切回可复用本服务结果；force 绕过译文缓存 |
| V14 | 来源缓存过期、译文过期、调用记录过期；手动清理 | 过期内容不命中；清理不删媒体、备份、NfoCheck 状态；失败不进入成功译文缓存 |
| V15 | 调用记录分页 / 筛选 / 详情 / 删除 | 列表只取摘要；详情按需读取；删除独立于缓存；没有密钥、认证头或原始服务报错 |
| V16 | 保存配置、清缓存与活动批次交错；停止 / 重载 | 活动批次拒绝配置突变；停止后不提交候选；资源释放后可重载；没有后台自动续写 |

## 6. NfoCheck、提交与 Emby

| 编号 | 输入 / 操作 | 必须观察到 |
| --- | --- | --- |
| N01 | 旧版配置、历史、冷却状态升级 | 新配置 version=3；保存前备份旧配置；普通规则语义与旧结果可读；不自动启动修复 |
| N02 | 缺语言 / 非目标语言 / 语言未知三种条件 | 按来源记录和输出哈希判断；字段名以中文(英文)显示；未知语言不伪装成已确认 |
| N03 | 两条同策略规则，分别选择 plot 和 tagline | 合并字段后只执行一次候选流程；未选字段保持不变 |
| N04 | 两条不同策略同时命中；另有图片任务 | NFO 显示策略冲突并保留原文件；图片仍可继续 |
| N05 | translate / nfo_translate；同时命中普通 NFO 重建 | 仅翻译修改所选节点；重建使用官方候选；同轮不会经全局翻译钩子重复翻译 |
| N06 | 缺少 NFO 选择 translate；损坏 XML；错误根或 ID | 明确要求重建或转人工；无错误身份写入；原文件不被无效候选覆盖 |
| N07 | plot 成功、tagline 限流，随后继续 | plot 原样保留；tagline 保留待办及时间；恢复后仅请求未完成字段 |
| N08 | nfo_translate 部分完成后停止并继续 | 持久化生成状态；文件版本未变时不再次重建已提交 NFO；图片剩余任务保留 |
| N09 | 服务 / 策略更换；规则删除；文件外部修改 | 重新判断语义版本；不沿用不匹配的冷却或已完成标记；删除规则不复活旧翻译动作 |
| N10 | 无原文、鉴权错误、已手改三类未完成字段 | 不增加普通“来源无改善”计数；无原文延后复查；手改保留并显示人工状态 |
| N11 | 选中条目普通重试 / force / overwrite；不提供 ids | 普通重试仅补齐；force 绕过译文缓存；overwrite 仅按明确选择生效；缺 IDs 的覆盖请求拒绝 |
| N12 | 试运行、仅报告规则、服务不可用 | 试运行不调用翻译供应商、不写媒体、不刷新 Emby；可查询 TMDB 语言记录；不可用原因可见 |
| N13 | 备份开 / 关；备份失败；提交期间文件修改 | 遵循现有设置；备份或指纹检查失败时不覆盖；缓存成功不等于文件成功 |
| N14 | 意图落盘后、文件提交后、报告保存前停止或中断 | 重启根据候选文件哈希认领已提交来源记录；不认领外部改写；资产状态可恢复 |
| N15 | 恢复 NFO 备份；之后巡检 / 翻译 | 清除该文件的旧翻译来源记录和未完成意图；重新判断恢复后的实际内容 |
| N16 | 仅 outline 变化；Emby 模式 changed | 本地完成，不新增元数据刷新；已有独立待同步任务不丢失 |
| N17 | 分别只改 title / plot / tagline | 定向刷新正确条目；分别核验 Name / Overview / Taglines；不要求未选文字改变 |
| N18 | Emby 离线、刷新后未采用、字段锁定、最新身份冲突 | 待同步独立保留；不得把 POST 成功计为已验证；沿用 D-01 冲突检查 |
| N19 | 删除原运行记录后重试待同步 | 不重新翻译或写媒体；只处理已提交版本的 Emby 同步 |
| N20 | 图片、备份、工作流、汇总通知、旧历史删除回归 | 既有行为保持；通知描述部分完成，不将未完成翻译统计为全部成功 |

对于纯文字补齐，仅验证 XML、根和身份，不以无关的完整性条件否决候选。重建 NFO 继续要求满足产生重建动作的非语言条件；如果官方候选本身不合格，整份候选不得提交。语言条件本身由逐字段状态判断。

## 7. 宿主、界面与交付

| 编号 | 操作 | 必须观察到 |
| --- | --- | --- |
| H01 | 独立 MoviePilot 安装两插件，禁用 / 启用 / 重载 | Vue 远程模块名称和目录正确；无跨插件入口串用；设置和密钥重载保留 |
| H02 | 开启官方增强，正常刮削；模拟供应商失败 | 官方生成先执行；成功仅增强选择字段；失败返回官方原文候选；不递归调用自身 |
| H03 | 另一插件声明 metadata_nfo；开启 / 关闭增强 | 冲突列表可见；有冲突不接管管道；关闭后使用宿主默认行为 |
| H04 | 非管理员访问设置、测试、预览、历史、删除、清缓存 | 全部拒绝；不能使用原始请求绕过前端限制 |
| H05 | 桌面与移动端编辑策略、语言字段、密钥和预览 | 中文标签完整、字段选择可用；预览所选策略不被保存动作重置；无 JS 异常 |
| H06 | 历史翻页、请求未完成时切换页面或卸载 | 结果不覆盖已离开页面；列表不预加载全部详情；删除后分页正确 |
| H07 | 五家实际服务最小样例（按账号实际可用模型） | 地址、认证、模型与输出模式匹配；记录实际字符/token 用量；模拟通过不替代真实兼容性 |
| H08 | 空目录 npm ci、两套构建、重复打包 | 安装可复现；ZIP 内容、CRC、版本和 SHA256 正确；同一输入重复打包字节一致 |
| H09 | 用旧 dist、错插件 build-meta 打包 | 拒绝生成新版本安装包；无 secrets.json、SQLite、媒体数据进入 ZIP |

## 8. 复验顺序与完成条件

1. 本地适配器 / 业务夹具：先 T、V，再 N；记录每个失败的最小复现输入。
2. 执行既有后端回归及与本次变动相关的 1.1.0 验收用例，尤其备份、原子提交、停止续跑、身份检查、脱敏、旧待同步迁移。对语义有意变化的夹具明确注明变更，不用旧断言逼产品回退。
3. 空环境依赖安装、类型检查、双前端构建和双包检查；验证源码版本与打包版本一致。
4. 独立 MoviePilot / Emby 实例完成 H 与 N 的真实集成项；真实翻译服务按账号可用情况单独列出通过、未执行及限制。
5. 输出新报告、失败清单、源码和产物 SHA256。无压测要求；本版是否允许安装由这份新验收结果决定，不引用本轮不存在的“测试通过”。

## 1.0.1 配置界面补充（功能测试未执行）

- 配置弹窗顶部“关闭页面”向宿主发送 close；加载或请求期间也可关闭，关闭不保存草稿、不停止后台巡检。
- 当前服务切换后编辑区跟随；单独编辑其他服务时，明确展示当前使用和正在编辑的服务，测试按钮显示实际测试对象。
- API Key 覆盖未配置、已保存、新输入待保存、删除待保存、撤销删除五种状态；显示按钮仅显示本次输入，不能读取旧密钥。
- 桌面与窄屏检查固定关闭入口、密钥输入换行、导航换行、输入控件宽度和键盘焦点。
- 清理缓存后保留尚未保存的设置和密钥输入。
