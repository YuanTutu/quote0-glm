#!/usr/bin/env python3
"""quote0-glm — 把 GLM（智谱）Coding Plan 余量推送到 Quote/0 电子墨水屏。

改造自 ajaxjiang96/quote0-burnout（MIT）的架构：provider 抓数据 →
snapshot → 296×152 纯黑白像素渲染 → Dot 开放平台 Image API 推送。

用法：
  python quote0_glm.py               # 拉取 + 推送（Image API）
  python quote0_glm.py --preview     # 只渲染预览图，不推送
  python quote0_glm.py --text        # Text API 纯文字模式
  python quote0_glm.py --check       # 自检（环境/接口/渲染），不推送
  python quote0_glm.py --debug-json  # 打印快照 JSON
  python quote0_glm.py --list-tasks  # 列出设备的 fixed/loop 卡片槽位
  python quote0_glm.py --interval 5m # 自调度循环（最低 60s）
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

import glm
from render import render_image

_HERE = Path(__file__).parent
API_BASE = "https://dot.mindreset.tech"
SNAPSHOT_CACHE_PATH = _HERE / "tmp" / "last_snapshot.json"


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _now() -> datetime:
    """渲染时间戳用的当前时间：优先 DISPLAY_TZ 指定时区（如 Asia/Shanghai），
    否则用系统本地时间。GitHub Actions 运行器是 UTC，云端跑必须显式设置。"""
    tz_name = os.environ.get("DISPLAY_TZ", "").strip()
    if tz_name:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz_name))
        except Exception:
            pass
    return datetime.now()


QUOTE0_API_KEY      = _env("QUOTE0_API_KEY")
QUOTE0_DEVICE_ID    = _env("QUOTE0_DEVICE_ID")
QUOTE0_IMAGE_TASK_KEY = _env("QUOTE0_IMAGE_TASK_KEY")
QUOTE0_TEXT_TASK_KEY  = _env("QUOTE0_TEXT_TASK_KEY")
QUOTE0_REFRESH_NOW = _env("QUOTE0_REFRESH_NOW", "true").lower() == "true"
QUOTE0_SWITCH_NEXT = _env("QUOTE0_SWITCH_NEXT", "true").lower() == "true"
REFRESH_INTERVAL_ENV = _env("REFRESH_INTERVAL") or _env("INTERVAL")
QUOTE0_PREVIEW_PATH = _env("QUOTE0_PREVIEW_PATH") or str(_HERE / "tmp" / "preview.png")


# ── 快照（带缓存兜底：断网时上一次成功数据 + "*" 标记） ─────────────────────

def build_snapshot() -> dict:
    raw = glm.get_usage()
    sn = glm.build_snapshot(raw)
    snap = {
        "glm": sn,
        "updated_at": _now().strftime("%H:%M"),
        "_cached": False,
    }

    if sn.get("ok"):
        try:
            SNAPSHOT_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            SNAPSHOT_CACHE_PATH.write_text(json.dumps(snap, indent=2), encoding="utf-8")
        except OSError:
            pass
        return snap

    try:
        cached = json.loads(SNAPSHOT_CACHE_PATH.read_text(encoding="utf-8"))
        if cached.get("glm", {}).get("ok"):
            cached["updated_at"] = snap["updated_at"] + "*"
            cached["_cached"] = True
            return cached
    except (OSError, ValueError):
        pass
    return snap


# ── 推送 ─────────────────────────────────────────────────────────────────────

def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {QUOTE0_API_KEY}"}


def _resolve_image_task() -> tuple[str | None, str | None]:
    """探测设备上 Image API 卡片在哪个列表：返回 (taskType, taskKey)。

    优先 loop（refreshNow 立即刷新 + /next 切换都只对 loop 有效），
    其次 fixed。都找不到返回 (None, None)——卡片在 App 里被挪动或删除后
    推送仍能自动找到正确槽位，不再依赖手动配置 taskKey。"""
    for tt in ("loop", "fixed"):
        try:
            r = requests.get(
                f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/{tt}/list",
                headers=_auth_headers(), timeout=10)
            if not r.ok:
                continue
            data = r.json()
            if isinstance(data, list):
                for task in data:
                    if isinstance(task, dict) and task.get("type") == "IMAGE_API":
                        return tt, task.get("key")
        except (requests.RequestException, ValueError):
            continue
    return None, None


def push_image(png_bytes: bytes) -> dict:
    url = f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/image"

    task_type, task_key = _resolve_image_task()
    if task_type is None:
        # 探测失败（网络问题或卡片真没了）：按 loop 默认推，
        # 让服务端返回带指引的 404 而不是静默错投
        task_type = "loop"
        task_key = QUOTE0_IMAGE_TASK_KEY or None

    payload = {
        "taskType": task_type,
        # 官方文档：refreshNow 只对 loop 生效，fixed 卡片按自身节奏刷新
        "refreshNow": QUOTE0_REFRESH_NOW and task_type == "loop",
        "image": base64.b64encode(png_bytes).decode(),
        "ditherType": "NONE",   # 纯黑白文字图，关抖动防噪点（官方文档建议）
        "border": 0,
    }
    if task_key:
        payload["taskKey"] = task_key
    r = requests.post(url, json=payload, headers=_auth_headers(), timeout=20)
    try:
        body = r.json()
    except ValueError:
        body = {"_raw": r.text}
    return {"ok": r.ok, "status": r.status_code, "body": body,
            "task_type": task_type, "task_key": task_key}


def push_text(message: str) -> dict:
    url = f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/text"
    payload = {
        "refreshNow": QUOTE0_REFRESH_NOW,
        "message": message,
        "signature": _now().strftime("%H:%M"),
    }
    if QUOTE0_TEXT_TASK_KEY:
        payload["taskKey"] = QUOTE0_TEXT_TASK_KEY
    r = requests.post(
        url,
        json=payload,
        headers={**_auth_headers(), "Content-Type": "application/json"},
        timeout=20,
    )
    try:
        body = r.json()
    except ValueError:
        body = {"_raw": r.text}
    return {"ok": r.ok, "status": r.status_code, "body": body}


def switch_next() -> dict:
    """推送后切换到下一张卡片，让设备立刻显示刚更新的内容。"""
    url = f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/next"
    try:
        r = requests.post(url, headers=_auth_headers(), timeout=10)
        return {"ok": r.ok, "status": r.status_code}
    except requests.RequestException as e:
        return {"ok": False, "status": f"network: {type(e).__name__}"}


# ── 主流程 ───────────────────────────────────────────────────────────────────

def run(preview: bool = False, text_mode: bool = False) -> bool:
    snap = build_snapshot()
    sn = snap["glm"]
    cached_tag = " (cached)" if snap.get("_cached") else ""
    print(f"GLM: {glm.format_text(sn)}{cached_tag}")

    if preview:
        png = render_image(snap)
        Path(QUOTE0_PREVIEW_PATH).parent.mkdir(parents=True, exist_ok=True)
        Path(QUOTE0_PREVIEW_PATH).write_bytes(png)
        print(f"Preview saved to {QUOTE0_PREVIEW_PATH}")
        print("--preview only, skipping push")
        return True

    if text_mode:
        result = push_text(glm.format_text(sn))
    else:
        png = render_image(snap)
        # 推送模式也留一份预览（GitHub Actions 产物/本地排障都能看）
        try:
            Path(QUOTE0_PREVIEW_PATH).parent.mkdir(parents=True, exist_ok=True)
            Path(QUOTE0_PREVIEW_PATH).write_bytes(png)
        except OSError:
            pass
        result = push_image(png)
        print(f"image task: {result.get('task_type')}/{result.get('task_key')}")
        # /next 切换显示只对 loop 卡片有意义；fixed 卡片按设备自身节奏刷新
        if result.get("ok") and QUOTE0_SWITCH_NEXT and result.get("task_type") == "loop":
            nxt = switch_next()
            if not nxt.get("ok"):
                print(f"warning: /next switch failed (HTTP {nxt.get('status')})", file=sys.stderr)

    output = {"ok": result.get("ok"), "status": result.get("status"),
              "message": result.get("body", {}).get("message", "")
              if isinstance(result.get("body"), dict) else str(result.get("body"))}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        print(f"\n⚠️  Push failed (HTTP {result.get('status')}): {output['message']}", file=sys.stderr)
        return False
    return True


# ── 自检 ─────────────────────────────────────────────────────────────────────

def check() -> int:
    print("quote0-glm check\n")
    failures = 0

    print("Environment:")
    for name, val, required in [
        ("QUOTE0_API_KEY", QUOTE0_API_KEY, True),
        ("QUOTE0_DEVICE_ID", QUOTE0_DEVICE_ID, True),
        ("GLM_API_KEY", glm.GLM_API_KEY, True),
        ("GLM_PLAN", glm.GLM_PLAN or "cn", False),
    ]:
        if val:
            shown = (val[:3] + "...") if len(val) > 6 else val
            print(f"  {name:<22} OK {shown}")
        elif required:
            print(f"  {name:<22} FAIL missing")
            failures += 1
        else:
            print(f"  {name:<22} OK optional / missing")

    print("\nGLM:")
    glm_ok = False
    if glm.is_configured():
        sn = glm.build_snapshot(glm.get_usage())
        if sn.get("ok"):
            parts = [f"plan={sn.get('plan') or '?'}"]
            s = sn.get("short_used_percent")
            l = sn.get("long_used_percent")
            if s is not None:
                parts.append(f"5h left {100 - s}%")
            if l is not None:
                parts.append(f"Wk left {100 - l}%")
            mcp = sn.get("mcp")
            if mcp:
                parts.append(f"MCP {mcp.get('remaining')}/{mcp.get('total')}")
            print(f"  usage                  OK {' '.join(parts)}")
            glm_ok = True
        else:
            print(f"  usage                  FAIL {sn.get('raw_status')}")
    else:
        print("  usage                  FAIL no GLM_API_KEY")

    print("\nRender:")
    if glm_ok:
        try:
            png = render_image(build_snapshot())
            Path(QUOTE0_PREVIEW_PATH).parent.mkdir(parents=True, exist_ok=True)
            Path(QUOTE0_PREVIEW_PATH).write_bytes(png)
            print(f"  image                  OK {QUOTE0_PREVIEW_PATH}")
        except Exception as e:
            print(f"  image                  FAIL {e}")
            failures += 1
    else:
        print("  image                  FAIL no data to render")

    print("\nQuote/0:")
    if QUOTE0_API_KEY and QUOTE0_DEVICE_ID:
        try:
            r = requests.get(
                f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/fixed/list",
                headers=_auth_headers(), timeout=10)
            print(f"  endpoint               {'OK' if r.ok else 'FAIL'} HTTP {r.status_code}")
            if not r.ok:
                failures += 1
        except Exception as e:
            print(f"  endpoint               FAIL {e}")
            failures += 1
    else:
        print("  endpoint               FAIL QUOTE0_API_KEY or QUOTE0_DEVICE_ID missing")
        failures += 1

    print(f"\nResult: {'OK' if failures == 0 else f'FAIL ({failures} error(s))'}")
    return 0 if failures == 0 else 1


# ── 列出卡片槽位 ─────────────────────────────────────────────────────────────

def list_tasks(task_type: str = "") -> int:
    if not QUOTE0_API_KEY or not QUOTE0_DEVICE_ID:
        print("Error: QUOTE0_API_KEY and QUOTE0_DEVICE_ID are required", file=sys.stderr)
        return 1
    for tt in ([task_type] if task_type else ["fixed", "loop"]):
        try:
            r = requests.get(
                f"{API_BASE}/api/authV2/open/device/{QUOTE0_DEVICE_ID}/{tt}/list",
                headers=_auth_headers(), timeout=10)
            if not r.ok:
                print(f"{tt}:  HTTP {r.status_code}", file=sys.stderr)
                continue
            data = r.json()
            print(f"{tt}:")
            if not isinstance(data, list):
                print(json.dumps(data, ensure_ascii=False, indent=2))
                continue
            if not data:
                print("  (empty)")
            for task in data:
                if isinstance(task, dict):
                    line = f"  {task.get('type', '?'):<12} {task.get('key', '?')}"
                    if task.get("title") or task.get("name"):
                        line += f"  {task.get('title') or task.get('name')}"
                    print(line)
                else:
                    print(f"  {task}")
        except Exception as e:
            print(f"{tt}:  error — {e}", file=sys.stderr)
    return 0


# ── CLI ──────────────────────────────────────────────────────────────────────

def parse_interval(raw) -> int | None:
    if raw is None or not str(raw).strip():
        return None
    if isinstance(raw, (int, float)):
        sec = int(raw)
    else:
        s = str(raw).strip().lower()
        if s.endswith("s"):
            sec = int(float(s[:-1]))
        elif s.endswith("m"):
            sec = int(float(s[:-1]) * 60)
        elif s.endswith("h"):
            sec = int(float(s[:-1]) * 3600)
        else:
            sec = int(float(s))
    if sec < 60:
        raise ValueError(f"Interval {sec}s is below the minimum allowed (60s)")
    return sec


def main():
    parser = argparse.ArgumentParser(description="Push GLM usage to Quote/0 display")
    parser.add_argument("--preview", action="store_true",
                        help=f"Save preview PNG to {QUOTE0_PREVIEW_PATH} and skip push")
    parser.add_argument("--text", action="store_true",
                        help="Use Text API instead of Image API")
    parser.add_argument("--check", action="store_true", help="Run self-check, no push")
    parser.add_argument("--debug-json", action="store_true", help="Print snapshot JSON")
    parser.add_argument("--list-tasks", nargs="?", const="", metavar="TYPE",
                        help="List task slots: no arg = fixed+loop, 'fixed', 'loop'")
    parser.add_argument("--interval", default=None, metavar="5m",
                        help="Self-scheduling loop (e.g. 60, 5m, 1h; minimum 60s)")
    args = parser.parse_args()

    if args.check:
        sys.exit(check())
    if args.list_tasks is not None:
        sys.exit(list_tasks(args.list_tasks))
    if args.debug_json:
        print(json.dumps(build_snapshot(), ensure_ascii=False, indent=2))
        sys.exit(0)

    interval = None
    raw = args.interval if args.interval is not None else REFRESH_INTERVAL_ENV
    if raw is not None:
        try:
            interval = parse_interval(raw)
        except ValueError as e:
            print(f"Error: invalid --interval: {e}", file=sys.stderr)
            sys.exit(1)

    if interval is not None:
        print(f"Starting self-scheduling loop (interval: {interval}s). Ctrl+C to stop.")
        try:
            while True:
                start = time.time()
                try:
                    run(preview=args.preview, text_mode=args.text)
                except Exception as e:
                    print(f"Error during update cycle: {e}", file=sys.stderr)
                time.sleep(max(0.0, interval - (time.time() - start)))
        except KeyboardInterrupt:
            print("\nExiting.")
            sys.exit(0)
    else:
        sys.exit(0 if run(preview=args.preview, text_mode=args.text) else 1)


if __name__ == "__main__":
    main()
