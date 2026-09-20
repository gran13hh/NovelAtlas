# NovelAtlas Harness 插件

为 DeepSeek Harness 提供小说分析 Skill，以及上传、检索、引用核验、任务查询、取消和报告导出工具。分析任务由本地 NovelAtlas 服务执行。

## 安装

需要 Node.js 24、pnpm 和正在运行的 NovelAtlas 后端：

```sh
cd plugins/deepseek-harness
npm ci
npm pack --pack-destination /private/tmp
npx @deepseek-ai/dsh@0.1.5-rc.1 plugin --profile web add /private/tmp/dsh-novelatlas-0.1.2.tgz
npx @deepseek-ai/dsh@0.1.5-rc.1 web
```

默认连接 `http://127.0.0.1:8000`。自定义连接可创建 YAML patch，并通过 Harness `--patch` 参数加载：

```yaml
- id: novelatlas
  config:
    apiBaseUrl: http://127.0.0.1:8000
    timeoutMs: 30000
    exportDirectory: ./novelatlas-exports
```

在 NovelAtlas 工作台上传 TXT 后，向 Harness 提出：

> 使用 novelatlas-analyze Skill 分析任务 <task_id> 的人物关系与剧情冲突，核对原文证据，完成后导出 HTML。

模型密钥在服务端配置。引用核验只确认原句与来源匹配；报告仍需人工确认。模型驱动的自然语言演示与真实 DeepSeek 联调尚待验证。
