#!/usr/bin/env python3
"""aicurl - 给 OpenAI-compatible API 用的 curl：发请求、存模板、重放。

纯标准库。API key 只从环境变量 OPENAI_API_KEY（或 --api-key）读取，
从不在输出中打印完整 key。
"""
import argparse
import json
import os
import sys
import urllib.request
import urllib.error

VERSION = "0.1.0"
DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_CONFIG_DIR = os.path.expanduser("~/.config/aicurl")
TIMEOUT = 120


def err(msg, code=1):
    sys.stderr.write("error: %s\n" % msg)
    sys.exit(code)


def get_key(args):
    key = args.api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        err("未找到 API key。请先设置环境变量 OPENAI_API_KEY，或用 --api-key 传入。")
    return key


def mask_key(key):
    if len(key) <= 7:
        return "Bearer ***"
    return "Bearer ***" + key[-4:]


def requests_path(config_dir):
    return os.path.join(config_dir or DEFAULT_CONFIG_DIR, "requests.json")


def load_templates(config_dir):
    path = requests_path(config_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        err("读取模板文件失败（%s）：%s" % (path, e))
    if not isinstance(data, dict):
        err("模板文件格式损坏：顶层不是对象")
    return data


def save_templates(config_dir, data):
    path = requests_path(config_dir)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def build_body(model, system, prompt, temperature, max_tokens):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    body = {"model": model, "messages": messages}
    if temperature is not None:
        body["temperature"] = temperature
    if max_tokens is not None:
        body["max_tokens"] = max_tokens
    return body


def do_request(base_url, key, body, stream=False):
    url = base_url.rstrip("/") + "/chat/completions"
    if stream:
        body = dict(body)
        body["stream"] = True
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data,
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + key},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "replace")[:500]
        except Exception:
            detail = ""
        err("API 返回 HTTP %d：%s" % (e.code, detail))
    except urllib.error.URLError as e:
        err("网络请求失败：%s" % e.reason)
    if stream:
        return resp, None
    try:
        payload = json.loads(resp.read().decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        err("响应不是合法 JSON：%s" % e)
    return resp, payload


def extract_text(payload):
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        err("响应结构异常，取不到 choices[0].message.content")


def cmd_chat(args):
    key = get_key(args)
    body = build_body(args.model, args.system, args.prompt,
                      args.temperature, args.max_tokens)
    url = (args.base_url or DEFAULT_BASE_URL).rstrip("/") + "/chat/completions"
    if args.dry_run:
        print("===== 将要发送的 HTTP 请求（dry-run，未调用网络）=====")
        print("POST " + url)
        print("Authorization: " + mask_key(key))
        print("Content-Type: application/json")
        print()
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0
    if args.stream:
        resp, _ = do_request(args.base_url or DEFAULT_BASE_URL, key, body, stream=True)
        full = []
        try:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue
                try:
                    delta = chunk["choices"][0]["delta"].get("content", "")
                except (KeyError, IndexError, TypeError):
                    continue
                if delta:
                    sys.stdout.write(delta)
                    sys.stdout.flush()
                    full.append(delta)
        finally:
            resp.close()
        sys.stdout.write("\n")
        return 0
    _, payload = do_request(args.base_url or DEFAULT_BASE_URL, key, body)
    if args.raw:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.json:
        print(json.dumps({"model": args.model, "reply": extract_text(payload)},
                         ensure_ascii=False, indent=2))
    else:
        print(extract_text(payload))
    return 0


def cmd_save(args):
    templates = load_templates(args.config_dir)
    tpl = {}
    if args.model:
        tpl["model"] = args.model
    if args.system:
        tpl["system"] = args.system
    if args.temperature is not None:
        tpl["temperature"] = args.temperature
    if args.max_tokens is not None:
        tpl["max_tokens"] = args.max_tokens
    if args.base_url:
        tpl["base_url"] = args.base_url
    templates[args.name] = tpl
    save_templates(args.config_dir, templates)
    print("已保存模板「%s」→ %s" % (args.name, requests_path(args.config_dir)))
    return 0


def apply_overrides(tpl, overrides):
    tpl = dict(tpl)
    for item in overrides or []:
        if "=" not in item:
            err("--set 格式应为 key=value，收到：%s" % item)
        k, v = item.split("=", 1)
        k = k.strip()
        if k in ("temperature",):
            try:
                v = float(v)
            except ValueError:
                err("--set temperature 需要数字，收到：%s" % v)
        elif k in ("max_tokens",):
            try:
                v = int(v)
            except ValueError:
                err("--set max_tokens 需要整数，收到：%s" % v)
        tpl[k] = v
    return tpl


def cmd_run(args):
    templates = load_templates(args.config_dir)
    if args.name not in templates:
        err("没有这个模板：%s（用 `aicurl list` 查看）" % args.name)
    tpl = apply_overrides(templates[args.name], args.set)
    key = get_key(args)
    base_url = args.base_url or tpl.get("base_url") or DEFAULT_BASE_URL
    model = args.model or tpl.get("model") or "gpt-4o-mini"
    body = build_body(model, tpl.get("system"), args.prompt,
                      tpl.get("temperature"), tpl.get("max_tokens"))
    url = base_url.rstrip("/") + "/chat/completions"
    if args.dry_run:
        print("===== 将要发送的 HTTP 请求（dry-run，未调用网络）=====")
        print("POST " + url)
        print("Authorization: " + mask_key(key))
        print("Content-Type: application/json")
        print()
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0
    _, payload = do_request(base_url, key, body)
    if args.raw:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(extract_text(payload))
    return 0


def cmd_list(args):
    templates = load_templates(args.config_dir)
    if not templates:
        print("还没有保存任何模板。用 `aicurl save <name> ...` 创建一个。")
        return 0
    for name in sorted(templates):
        tpl = templates[name]
        desc = "model=%s" % tpl.get("model", "(默认)")
        if tpl.get("system"):
            desc += "，system=%.20s…" % tpl["system"] if len(tpl["system"]) > 20 else "，system=" + tpl["system"]
        print("%s: %s" % (name, desc))
    return 0


def cmd_show(args):
    templates = load_templates(args.config_dir)
    if args.name not in templates:
        err("没有这个模板：%s" % args.name)
    print(json.dumps({args.name: templates[args.name]}, ensure_ascii=False, indent=2))
    return 0


def cmd_delete(args):
    templates = load_templates(args.config_dir)
    if args.name not in templates:
        err("没有这个模板：%s" % args.name)
    del templates[args.name]
    save_templates(args.config_dir, templates)
    print("已删除模板「%s」" % args.name)
    return 0


def common_api_args(p):
    p.add_argument("--model", default="gpt-4o-mini", help="模型名（默认 gpt-4o-mini）")
    p.add_argument("--base-url", default=None, help="API base URL（默认 https://api.openai.com/v1）")
    p.add_argument("--api-key", default=None, help="API key（默认读 OPENAI_API_KEY）")
    p.add_argument("--temperature", type=float, default=None)
    p.add_argument("--max-tokens", type=int, default=None)
    p.add_argument("--dry-run", action="store_true", help="只打印请求，不联网")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="aicurl",
                                 description="给 OpenAI-compatible API 用的 curl：发请求、存模板、重放。")
    ap.add_argument("--version", action="version", version="aicurl " + VERSION)
    ap.add_argument("--config-dir", default=None, help="模板存放目录（默认 ~/.config/aicurl）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("chat", help="发一次 chat 请求")
    p.add_argument("prompt", help="用户问题")
    p.add_argument("--system", default=None, help="system prompt")
    p.add_argument("--stream", action="store_true", help="SSE 流式输出")
    p.add_argument("--raw", action="store_true", help="打印完整 JSON 响应")
    p.add_argument("--json", action="store_true", help="打印结构化 JSON")
    common_api_args(p)
    _add_config_dir(p)
    p.set_defaults(func=cmd_chat)

    p = sub.add_parser("save", help="保存一个请求模板")
    p.add_argument("name", help="模板名")
    p.add_argument("--system", default=None)
    common_api_args(p)
    _add_config_dir(p)
    p.set_defaults(func=cmd_save)

    p = sub.add_parser("run", help="用模板发请求")
    p.add_argument("name", help="模板名")
    p.add_argument("prompt", help="用户问题")
    p.add_argument("--set", action="append", default=[], help="覆盖模板参数，如 --set temperature=0")
    p.add_argument("--raw", action="store_true")
    common_api_args(p)
    _add_config_dir(p)
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("list", help="列出所有模板")
    _add_config_dir(p)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("show", help="查看模板详情")
    p.add_argument("name")
    _add_config_dir(p)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("delete", help="删除模板")
    p.add_argument("name")
    _add_config_dir(p)
    p.set_defaults(func=cmd_delete)

    args = ap.parse_args(argv)
    return args.func(args)


def _add_config_dir(p):
    # default=SUPPRESS：只在用户显式传入时覆盖全局 --config-dir，
    # 避免子命令的默认值 None 盖掉全局传入的值
    p.add_argument("--config-dir", default=argparse.SUPPRESS,
                   help="模板存放目录（默认 ~/.config/aicurl）")


if __name__ == "__main__":
    sys.exit(main())
