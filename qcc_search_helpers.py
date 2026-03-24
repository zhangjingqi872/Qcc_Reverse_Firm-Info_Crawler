# -*- coding: utf-8 -*-
"""企查查 searchMulti 公共逻辑（供 02 单条调试与批量脚本复用）。"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional, Tuple

import execjs
import requests
from lxml import etree

from encode_url import encode_url_chinese


def body_json_like_stringify(obj: dict) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=True)


def load_js_compiler(base_dir: str) -> Any:
    js_path = os.path.join(base_dir, "02_企查查_header加密逻辑.js")
    with open(js_path, "r", encoding="utf-8") as f:
        return execjs.compile(f.read())


def fetch_pid_tid(
    session: requests.Session,
    key_word: str,
    cookie: str,
    user_agent: str,
) -> Tuple[str, Optional[str], str]:
    """
    访问搜索页，解析 window.pid / window.tid。
    返回 (window_pid, window_tid_or_None, encode_main_url)
    """
    main_url = "https://www.qcc.com/web/search?key=" + key_word
    encode_main_url = encode_url_chinese(main_url)
    main_header = {
        "cookie": cookie,
        "referer": encode_main_url,
        "user-agent": user_agent,
    }
    response = session.get(main_url, headers=main_header)
    tree = etree.HTML(response.text)
    window_pid = tree.xpath("/html/body/script[1]/text()")[0]
    window_pid = window_pid.split(";")[0]
    m = re.search(r"window\.pid='(.*?)'", window_pid)
    if not m:
        raise RuntimeError("无法解析 window.pid")
    window_pid = m.group(1)
    m_tid = re.search(r"window\.tid\s*=\s*['\"]([^'\"]+)['\"]", response.text)
    window_tid = m_tid.group(1) if m_tid else None
    return window_pid, window_tid, encode_main_url


def fetch_pid_tid_by_url(
    session: requests.Session,
    page_url: str,
    cookie: str,
    user_agent: str,
) -> Tuple[str, Optional[str], str]:
    """
    访问任意页面（例如 firm 详情页），解析 window.pid / window.tid。
    返回 (window_pid, window_tid_or_None, encoded_page_url)
    """
    encoded_page_url = encode_url_chinese(page_url)
    page_header = {
        "cookie": cookie,
        "referer": encoded_page_url,
        "user-agent": user_agent,
    }
    response = session.get(page_url, headers=page_header)
    tree = etree.HTML(response.text)
    window_pid = tree.xpath("/html/body/script[1]/text()")[0]
    window_pid = window_pid.split(";")[0]
    m = re.search(r"window\.pid='(.*?)'", window_pid)
    if not m:
        raise RuntimeError("无法解析 window.pid")
    window_pid = m.group(1)
    m_tid = re.search(r"window\.tid\s*=\s*['\"]([^'\"]+)['\"]", response.text)
    window_tid = m_tid.group(1) if m_tid else None
    return window_pid, window_tid, encoded_page_url


def build_signed_headers(
    js_exec: Any,
    window_pid: str,
    window_tid: Optional[str],
    encode_main_url: str,
    page_index: int,
    key_word: str,
    cookie: str,
    user_agent: str,
) -> Tuple[Dict[str, str], str]:
    """返回 (headers, payload_str)。"""
    payload = {
        "searchKey": key_word,
        "pageIndex": page_index,
        "pageSize": 20,
    }
    payload_str = body_json_like_stringify(payload)
    search_multi_header: Dict[str, str] = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "cookie": cookie,
        "origin": "https://www.qcc.com",
        "priority": "u=1, i",
        "referer": encode_main_url + f"&p={page_index}",
        "user-agent": user_agent,
        "x-requested-with": "XMLHttpRequest",
        "x-pid": window_pid,
    }
    e: Dict[str, Any] = {
        "url": "/api/search/searchMulti",
        "method": "post",
        "data": payload,
        "headers": {
            "common": {"Accept": "application/json, text/plain, */*"},
            "delete": {},
            "get": {},
            "head": {},
            "post": {"Content-Type": "application/x-www-form-urlencoded"},
            "put": {"Content-Type": "application/x-www-form-urlencoded"},
            "patch": {"Content-Type": "application/x-www-form-urlencoded"},
            "X-Requested-With": "XMLHttpRequest",
            "x-pid": window_pid,
        },
        "baseURL": "https://www.qcc.com",
        "transformRequest": [None],
        "transformResponse": [None],
        "timeout": 0,
        "xsrfCookieName": "XSRF-TOKEN",
        "xsrfHeaderName": "X-XSRF-TOKEN",
        "maxContentLength": -1,
        "maxBodyLength": -1,
        "transitional": {
            "silentJSONParsing": True,
            "forcedJSONParsing": True,
            "clarifyTimeoutError": False,
        },
        "withCredentials": True,
    }
    if window_tid:
        e["tid"] = window_tid
    r = js_exec.call("main", e)
    search_multi_header[r["i"]] = r["u"]
    return search_multi_header, payload_str


def build_signed_headers_for_api(
    js_exec: Any,
    window_pid: str,
    window_tid: Optional[str],
    referer_url_encoded: str,
    api_path: str,
    method: str,
    payload: Optional[Dict[str, Any]],
    cookie: str,
    user_agent: str,
) -> Tuple[Dict[str, str], str]:
    """
    通用接口签名：适用于 /api/user/getUserCompany、/api/user/getSckrLimited 等。
    - api_path: 例如 /api/user/getUserCompany?keyNo=xxx
    - method: get / post
    - payload: GET 传 {}，POST 传真实 dict
    """
    data_obj: Dict[str, Any] = payload or {}
    payload_str = body_json_like_stringify(data_obj)
    method_l = method.lower().strip()

    headers: Dict[str, str] = {
        "accept": "application/json, text/plain, */*",
        "content-type": "application/json",
        "cookie": cookie,
        "origin": "https://www.qcc.com",
        "priority": "u=1, i",
        "referer": referer_url_encoded,
        "user-agent": user_agent,
        "x-requested-with": "XMLHttpRequest",
        "x-pid": window_pid,
    }
    e: Dict[str, Any] = {
        "url": api_path,
        "method": method_l,
        "data": data_obj,
        "headers": {
            "common": {"Accept": "application/json, text/plain, */*"},
            "delete": {},
            "get": {},
            "head": {},
            "post": {"Content-Type": "application/x-www-form-urlencoded"},
            "put": {"Content-Type": "application/x-www-form-urlencoded"},
            "patch": {"Content-Type": "application/x-www-form-urlencoded"},
            "X-Requested-With": "XMLHttpRequest",
            "x-pid": window_pid,
        },
        "baseURL": "https://www.qcc.com",
        "transformRequest": [None],
        "transformResponse": [None],
        "timeout": 0,
        "xsrfCookieName": "XSRF-TOKEN",
        "xsrfHeaderName": "X-XSRF-TOKEN",
        "maxContentLength": -1,
        "maxBodyLength": -1,
        "transitional": {
            "silentJSONParsing": True,
            "forcedJSONParsing": True,
            "clarifyTimeoutError": False,
        },
        "withCredentials": True,
    }
    if window_tid:
        e["tid"] = window_tid
    r = js_exec.call("main", e)
    headers[r["i"]] = r["u"]
    return headers, payload_str


def post_search_multi(
    session: requests.Session,
    headers: Dict[str, str],
    payload_str: str,
    timeout: int = 25,
) -> Dict[str, Any]:
    r = session.post(
        "https://www.qcc.com/api/search/searchMulti",
        headers=headers,
        data=payload_str.encode("utf-8"),
        timeout=timeout,
    )
    r.raise_for_status()
    return r.json()


def strip_html_em(s: Optional[str]) -> str:
    if not s:
        return ""
    return re.sub(r"<[^>]+>", "", str(s))


def summarize_result_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """从单条 Result 抽取常用字段（便于落盘）。"""
    ind = item.get("Industry") or {}
    area = item.get("Area") or {}
    hr = item.get("HitReason") or {}
    return {
        "KeyNo": item.get("KeyNo"),
        "Name": strip_html_em(item.get("Name")),
        "NameHtml": item.get("Name"),
        "CreditCode": item.get("CreditCode"),
        "OperName": item.get("OperName"),
        "Status": item.get("Status"),
        "ShortStatus": item.get("ShortStatus"),
        "StartDate": item.get("StartDate"),
        "Address": item.get("Address"),
        "RegistCapi": item.get("RegistCapi"),
        "ContactNumber": item.get("ContactNumber"),
        "Email": item.get("Email"),
        "EconKind": item.get("EconKind"),
        "Industry": ind.get("Industry") if isinstance(ind, dict) else None,
        "IndustryCode": ind.get("IndustryCode") if isinstance(ind, dict) else None,
        "Province": area.get("Province") if isinstance(area, dict) else None,
        "City": area.get("City") if isinstance(area, dict) else None,
        "County": area.get("County") if isinstance(area, dict) else None,
        "Score": item.get("Score"),
        "HitField": hr.get("Field") if isinstance(hr, dict) else None,
        "HitValueHtml": hr.get("Value") if isinstance(hr, dict) else None,
    }
