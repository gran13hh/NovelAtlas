# NovelAtlas

上传 TXT 长篇小说，生成可查看来源、人工修订并导出的全书细纲。

## 功能

- **长文本解析**：识别编码与章节，按 Token 预算分块、分批及分层汇总。
- **Agent 分析**：规划剧情、人物关系与世界观任务，分析跨章节关联。
- **原文核验**：按需检索章节证据，展示引用来源，区分事实、推断和不确定结论。
- **任务工作台**：实时进度、暂停与恢复、人工编辑；修改后重算受影响结果。
- **浏览器书架**：保存分析结果，支持继续未过期任务。
- **报告导出**：选择模块，导出 DOCX 或单文件 HTML。
- **模型与插件**：支持 Mock、OpenAI Responses、DeepSeek Chat Completions；提供 [DeepSeek Harness 插件](plugins/deepseek-harness/README.md)。

## 本地运行

需要 Python 3.11+ 和 Node.js。首次安装：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
npm --prefix apps/web ci
cp .env.example .env
```

启动前后端：

```sh
.venv/bin/python scripts/dev.py
```

macOS 也可双击 `start.command`。默认打开浏览器；按 `Ctrl+C` 同时停止服务。首次使用 Token 解析需要联网下载词表。

## 使用

1. 在模型配置中选择 Mock 离线体验，或填写远程模型配置。
2. 上传 TXT，检查章节解析并规划分析批次。
3. 选择 Agent 分析，填写目标并开始；查看进度、知识结果及原文证据。
4. 人工确认或修改结果，保存到书架，导出 DOCX/HTML。

示例文件：`tests/fixtures/novels/agent_demo.txt`。Mock 仅用于流程演示；引用原句存在不等于结论正确，重要结果需人工确认。真实 DeepSeek 联调仍待验证。

服务默认在本地以单 worker 运行，无登录功能。上传原文与中间产物默认保留一小时，可主动删除；浏览器书架保留分析结果。密钥建议写入私有 `.env`；浏览器主动保存的密钥以明文存放，仅适合可信设备。
