# aicurl

给 OpenAI-compatible API 用的 curl：发请求、存模板、重放。

```bash
aicurl chat "用三句话解释注意力机制" --model gpt-4o-mini
aicurl save translator --model gpt-4o-mini --system "你是中英翻译，只输出译文"
aicurl run translator "Hello world" --set temperature=0
```

## 安装

Python 3.10+，零依赖（纯标准库）：

```bash
export OPENAI_API_KEY="sk-..."
python -m aicurl chat "你好"
```

兼容任何 OpenAI 格式的 API：`--base-url http://localhost:11434/v1` 即可指向 Ollama
等本地服务。

## 用法

| 命令 | 说明 |
|---|---|
| `chat "问题"` | 发一次 chat 请求，直接打印回复文本 |
| `save <name> ...` | 把模型/system/temperature 存成模板（`~/.config/aicurl/requests.json`） |
| `run <name> "问题"` | 用模板发请求，`--set temperature=0` 可覆盖参数 |
| `list` / `show <name>` / `delete <name>` | 管理模板 |

常用参数：`--model`、`--system`、`--temperature`、`--max-tokens`、`--base-url`、
`--api-key`、`--config-dir`（模板目录，测试时可指向临时目录）。

输出控制：`--raw`（完整 JSON）、`--json`（结构化）、`--stream`（SSE 流式逐字打印）、
`--dry-run`（只打印将要发送的 HTTP 请求，不联网；key 显示为 `Bearer ***后4位`）。

## 安全

- key 只从 `OPENAI_API_KEY` 或 `--api-key` 读取，从不写入模板文件；
- `--dry-run` 与报错信息中 key 恒为打码形态；
- 模板文件只存模型与参数，不存 key。

## 已知局限（诚实版）

- SSE 解析是最小实现：只处理 `data:` 行与 `[DONE]`，异常 chunk 直接跳过；
- 不是完整 HTTP 客户端：没有 header 自定义、multipart、重试逻辑；
- 真实 API 未做扣费实测，请求构造经本地 stub server 完整验证。
