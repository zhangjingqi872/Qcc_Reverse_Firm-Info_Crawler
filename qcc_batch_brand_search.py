# -*- coding: utf-8 -*-
"""
读取项目根目录 qcc_brand_to_company_map.json 中的工商全称，
对每个关键字调用企查查 searchMulti（逻辑同 02_逆向 header 加密.py），
只保留每条搜索的前 2 条结果并抽取常用字段，写入 qcc_brand_qcc_top2.json。

用法（在项目根或本目录执行均可）:
  python qcc_batch_brand_search.py
  python qcc_batch_brand_search.py --limit 5
  set QCC_COOKIE=你的cookie  （可选，覆盖脚本内默认）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Set

import requests

_BASE = os.path.dirname(os.path.abspath(__file__))
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

from qcc_search_helpers import (  # noqa: E402
    fetch_pid_tid,
    load_js_compiler,
    post_search_multi,
    build_signed_headers,
    summarize_result_item,
)

# 与 02 脚本一致；也可用环境变量 QCC_COOKIE 覆盖
DEFAULT_COOKIE = (
    "qcc_did=59355786-ceac-4883-a721-cd7c051f117f; "
    "UM_distinctid=19b6782e7637b4-062813c0c97a448-4c657b58-144000-19b6782e764ffd; "
    "_c_WBKFRo=La2Fe6vhhMAmoE6aJlvto7Tg6H2F4KsTprq4eIqV; "
    "QCCSESSID=e6b1367c646259b608da547c7f; "
    "CNZZDATA1254842228=1957431002-1766968191-%7C1774101026; "
    "acw_tc=781bad0717741823503704621e69bf9b7035fd67157e8c03c1b1edea7a4972"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36 Edg/139.0.0.0"
)

TOP_N = 2
MAP_FILENAME = "qcc_brand_to_company_map.json"
OUT_FILENAME = "qcc_brand_qcc_top2.json"


def project_root() -> str:
    return os.path.abspath(os.path.join(_BASE, ".."))


def load_keywords_from_map(path: str) -> List[str]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    names: Set[str] = set()
    bmap = data.get("brand_to_legal_name") or {}
    for v in bmap.values():
        if isinstance(v, str) and v.strip():
            names.add(v.strip())
    for ov in data.get("address_overrides") or []:
        qn = ov.get("qcc_legal_name")
        if isinstance(qn, str) and qn.strip():
            names.add(qn.strip())
    return sorted(names)


def main() -> None:
    ap = argparse.ArgumentParser(description="批量企查查 searchMulti，取前2条")
    ap.add_argument("--limit", type=int, default=0, help="仅跑前 N 个关键字（0 表示全部）")
    ap.add_argument("--sleep", type=float, default=1.8, help="两次请求间隔秒数")
    ap.add_argument(
        "--map",
        default=os.path.join(project_root(), MAP_FILENAME),
        help="映射表 JSON 路径",
    )
    ap.add_argument(
        "--out",
        default=os.path.join(project_root(), OUT_FILENAME),
        help="输出 JSON 路径",
    )
    args = ap.parse_args()

    cookie = os.environ.get("QCC_COOKIE", DEFAULT_COOKIE).strip()
    map_path = args.map
    if not os.path.isfile(map_path):
        print(f"找不到映射表: {map_path}")
        sys.exit(1)

    keywords = load_keywords_from_map(map_path)
    if args.limit and args.limit > 0:
        keywords = keywords[: args.limit]

    js_exec = load_js_compiler(_BASE)
    session = requests.Session()

    out_rows: List[Dict[str, Any]] = []
    for i, kw in enumerate(keywords):
        print(f"[{i+1}/{len(keywords)}] 搜索: {kw}")
        row: Dict[str, Any] = {
            "search_keyword": kw,
            "api_status": None,
            "message": None,
            "top2": [],
            "error": None,
        }
        try:
            window_pid, window_tid, encode_main_url = fetch_pid_tid(
                session, kw, cookie, USER_AGENT
            )
            headers, payload_str = build_signed_headers(
                js_exec,
                window_pid,
                window_tid,
                encode_main_url,
                1,
                kw,
                cookie,
                USER_AGENT,
            )
            data = post_search_multi(session, headers, payload_str)
            row["api_status"] = data.get("Status")
            row["message"] = data.get("message")
            if data.get("Status") != 200:
                row["error"] = data.get("message") or "api Status != 200"
                out_rows.append(row)
                time.sleep(args.sleep)
                continue
            result_list = data.get("Result") or []
            if not isinstance(result_list, list):
                result_list = []
            top = result_list[:TOP_N]
            row["top2"] = [summarize_result_item(x) for x in top]
        except Exception as e:
            row["error"] = str(e)
        out_rows.append(row)
        time.sleep(args.sleep)

    payload_out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_map": os.path.abspath(map_path),
        "top_n": TOP_N,
        "total_keywords": len(keywords),
        "results": out_rows,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload_out, f, ensure_ascii=False, indent=2)
    print(f"已写入: {args.out}")


if __name__ == "__main__":
    main()
