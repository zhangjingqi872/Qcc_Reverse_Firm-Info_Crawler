# -*- coding: utf-8 -*-
"""
纯 requests + BeautifulSoup 解析 qcc firm 页面基本信息。
不调用受限的 getUserCompany/getSckrLimited 接口。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from typing import Any, Dict, List

import requests
from bs4 import BeautifulSoup

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_COOKIE = (
    "qcc_did=59355786-ceac-4883-a721-cd7c051f117f; "
    "UM_distinctid=19b6782e7637b4-062813c0c97a448-4c657b58-144000-19b6782e764ffd; "
    "_c_WBKFRo=La2Fe6vhhMAmoE6aJlvto7Tg6H2F4KsTprq4eIqV; "
    "QCCSESSID=e6b1367c646259b608da547c7f; "
    "CNZZDATA1254842228=1957431002-1766968191-%7C1774186917; "
    "acw_tc=781bad7f17743194481344252e5abf28456c4fe0011a39b0428a4b36cbafd4"
)
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0"
)


def _clean_text(s: str) -> str:
    return " ".join((s or "").split())


def _norm_key(s: str) -> str:
    s = _clean_text(s)
    return s.replace(" ", "").replace("：", "").replace(":", "")


def _put_if_absent(kv: Dict[str, str], key: str, val: str) -> None:
    key = _norm_key(key)
    val = _clean_text(val)
    if not key or not val:
        return
    if key not in kv:
        kv[key] = val


def _parse_initial_state_from_html(html: str) -> Dict[str, Any]:
    """
    从页面源代码提取 window.__INITIAL_STATE__ 对象。
    """
    marker = "window.__INITIAL_STATE__"
    pos = html.find(marker)
    if pos < 0:
        return {}

    eq_pos = html.find("=", pos)
    if eq_pos < 0:
        return {}

    start = html.find("{", eq_pos)
    if start < 0:
        return {}

    # 用大括号配对提取 JSON，避免正则在复杂内容下截断。
    in_str = False
    escaped = False
    depth = 0
    end = -1
    i = start
    n = len(html)
    while i < n:
        ch = html[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        i += 1

    if end <= start:
        return {}

    raw = html[start:end]
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _extract_fields_from_initial_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 __INITIAL_STATE__.company.companyDetail 提取关键字段。
    """
    company = (state.get("company") or {}) if isinstance(state, dict) else {}
    detail = (company.get("companyDetail") or {}) if isinstance(company, dict) else {}
    if not isinstance(detail, dict) or not detail:
        return {"fields": {}, "legal_person": "", "found": False}

    kv: Dict[str, str] = {}
    contact = (detail.get("ContactInfo") or {}) if isinstance(detail.get("ContactInfo"), dict) else {}
    area = (detail.get("Area") or {}) if isinstance(detail.get("Area"), dict) else {}
    qcc_ind = (detail.get("QccIndustry") or {}) if isinstance(detail.get("QccIndustry"), dict) else {}
    industry_v3 = (detail.get("IndustryV3") or {}) if isinstance(detail.get("IndustryV3"), dict) else {}
    oper = (detail.get("Oper") or {}) if isinstance(detail.get("Oper"), dict) else {}

    _put_if_absent(kv, "企业名称", str(detail.get("Name") or ""))
    _put_if_absent(kv, "统一社会信用代码", str(detail.get("CreditCode") or ""))
    _put_if_absent(kv, "法定代表人", str(oper.get("Name") or ""))
    _put_if_absent(kv, "注册资本", str(detail.get("RegistCapi") or ""))
    _put_if_absent(kv, "企业类型", str(detail.get("EconKind") or ""))
    _put_if_absent(kv, "登记状态", str(detail.get("Status") or ""))
    _put_if_absent(kv, "注册地址", str(detail.get("Address") or ""))
    _put_if_absent(kv, "经营范围", str(detail.get("Scope") or ""))
    _put_if_absent(kv, "电话", str(contact.get("PhoneNumber") or ""))
    _put_if_absent(kv, "邮箱", str(contact.get("Email") or ""))
    _put_if_absent(kv, "官网", str(contact.get("WebSite") or ""))
    _put_if_absent(kv, "所属地区", "".join([str(area.get("Province") or ""), str(area.get("City") or ""), str(area.get("County") or "")]))
    _put_if_absent(kv, "企查查行业", str(qcc_ind.get("Dn") or qcc_ind.get("Cn") or ""))
    _put_if_absent(kv, "国标行业", str(industry_v3.get("SmallCategory") or industry_v3.get("MiddleCategory") or ""))
    _put_if_absent(kv, "英文名", str(detail.get("EnglishName") or ""))
    _put_if_absent(kv, "组织机构代码", str(detail.get("OrgNo") or ""))
    _put_if_absent(kv, "纳税人识别号", str(detail.get("TaxNo") or ""))

    legal_person = str(oper.get("Name") or "")
    return {"fields": kv, "legal_person": legal_person, "found": True}


def _cookie_header_to_list(cookie_header: str) -> List[Dict[str, Any]]:
    cookies: List[Dict[str, Any]] = []
    for part in cookie_header.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, value = part.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": ".qcc.com",
                "path": "/",
            }
        )
    return cookies


def fetch_firm_html_with_drissionpage(
    key_no: str,
    cookie: str,
    timeout: int = 25,
    wait_s: float = 4.5,
) -> Dict[str, Any]:
    """
    使用 DrissionPage 动态渲染 firm 页面后获取 html。
    依赖：pip install drissionpage
    """
    try:
        from DrissionPage import ChromiumOptions, ChromiumPage  # type: ignore[import-not-found]
    except Exception as e:
        return {"ok": False, "error": f"drissionpage_not_installed: {e}"}

    url = f"https://www.qcc.com/firm/{key_no}.html"
    page = None
    try:
        co = ChromiumOptions()
        co.set_argument("--headless=new")
        co.set_argument("--disable-blink-features=AutomationControlled")
        co.set_user_agent(USER_AGENT)
        page = ChromiumPage(co)
        # 设置 cookie（兼容不同版本 API）
        ck = _cookie_header_to_list(cookie)
        try:
            page.set.cookies(ck)  # 新版常见
        except Exception:
            try:
                page.cookies.set(ck)  # 兼容写法
            except Exception:
                pass

        page.get(url, timeout=timeout)
        # 等待目标块，若失败则继续返回当前 html 供诊断
        try:
            page.wait.ele("css:div.contact-info,div.cominfo-normal", timeout=wait_s)
        except Exception:
            pass
        html = page.html
        title = _clean_text(page.title or "")
        current_url = page.url
        return {"ok": True, "html": html, "title": title, "url": current_url}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    finally:
        if page is not None:
            try:
                page.quit()
            except Exception:
                pass


def extract_basic_info_from_firm_html(
    session: requests.Session,
    key_no: str,
    cookie: str,
    save_html: bool = False,
    html_dir: str = "",
) -> Dict[str, Any]:
    """
    从 firm 页面 HTML 中解析 cominfo-normal/contact-info 基本信息。
    纯 requests + BeautifulSoup，不执行 JS。
    """
    firm_url = f"https://www.qcc.com/firm/{key_no}.html"
    headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "cookie": cookie,
        "referer": "https://www.qcc.com/",
        "user-agent": USER_AGENT,
    }
    # 1) 先尝试 requests（静态）
    resp = session.get(firm_url, headers=headers, timeout=20)
    html = resp.text
    if save_html and html_dir:
        os.makedirs(html_dir, exist_ok=True)
        with open(os.path.join(html_dir, f"{key_no}.requests.html"), "w", encoding="utf-8") as f:
            f.write(html)

    soup = BeautifulSoup(html, "html.parser")
    kv: Dict[str, str] = {}
    legal_person = ""
    has_cominfo = soup.select_one("div.cominfo-normal table.ntable") is not None
    has_contact = soup.select_one("div.contact-info") is not None
    page_title = _clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
    blocked_reason = ""

    # 拦截页识别：405/登录页等
    low_html = html.lower()
    if "405.html" in (resp.url or "") or ("405" in page_title and not has_cominfo and not has_contact):
        blocked_reason = "blocked_405"
    elif ("登录" in page_title or "会员登录" in page_title or "login" in low_html) and not has_cominfo and not has_contact:
        blocked_reason = "blocked_login"

    # 优先从 __INITIAL_STATE__ 提取（最稳定）
    initial_state = _parse_initial_state_from_html(html)
    init_pick = _extract_fields_from_initial_state(initial_state)
    if init_pick.get("found"):
        kv.update(init_pick.get("fields") or {})
        legal_person = str(init_pick.get("legal_person") or "")

    # 2) requests 拿不到关键块，且 __INITIAL_STATE__ 也没拿到时，才尝试动态渲染
    used_drission = False
    drission_error = ""
    should_try_drission = (not has_cominfo and not has_contact and not kv)
    if should_try_drission:
        dr = fetch_firm_html_with_drissionpage(key_no, cookie)
        if dr.get("ok"):
            html2 = dr.get("html", "")
            if save_html and html_dir:
                os.makedirs(html_dir, exist_ok=True)
                with open(os.path.join(html_dir, f"{key_no}.drission.html"), "w", encoding="utf-8") as f:
                    f.write(html2)
            soup2 = BeautifulSoup(html2, "html.parser")
            has_cominfo2 = soup2.select_one("div.cominfo-normal table.ntable") is not None
            has_contact2 = soup2.select_one("div.contact-info") is not None
            if has_cominfo2 or has_contact2:
                used_drission = True
                soup = soup2
                html = html2
                has_cominfo = has_cominfo2
                has_contact = has_contact2
                page_title = _clean_text(str(dr.get("title") or page_title))
                if dr.get("url"):
                    resp_url = str(dr.get("url"))
                else:
                    resp_url = resp.url
                # 动态渲染后，再尝试一次 __INITIAL_STATE__ 提取（作为主来源）
                initial_state2 = _parse_initial_state_from_html(html2)
                init_pick2 = _extract_fields_from_initial_state(initial_state2)
                if init_pick2.get("found"):
                    kv.update(init_pick2.get("fields") or {})
                    if not legal_person:
                        legal_person = str(init_pick2.get("legal_person") or "")
            else:
                resp_url = resp.url
        else:
            drission_error = str(dr.get("error") or "")
            resp_url = resp.url
    else:
        resp_url = resp.url

    # cominfo-normal 表格（作为补充）
    table = soup.select_one("div.cominfo-normal table.ntable")
    if table:
        for tr in table.select("tr"):
            tds = tr.find_all("td", recursive=False)
            i = 0
            while i < len(tds) - 1:
                td_key = tds[i]
                classes = td_key.get("class") or []
                if "tb" not in classes:
                    i += 1
                    continue
                key = _norm_key(td_key.get_text(" ", strip=True))
                td_val = tds[i + 1]
                cv = td_val.select_one(".copy-value")
                if cv:
                    val = _clean_text(cv.get_text(" ", strip=True))
                else:
                    val = _clean_text(td_val.get_text(" ", strip=True))
                _put_if_absent(kv, key, val)
                if "法定代表人" in key and not legal_person:
                    a = td_val.select_one("a")
                    legal_person = _clean_text(a.get_text(" ", strip=True)) if a else val
                i += 2

    # contact-info 补充
    for line in soup.select("div.contact-info div.rline"):
        key = ""
        for tag in line.select(".need-copy-field"):
            t = _clean_text(tag.get_text(" ", strip=True))
            if "：" in t or ":" in t:
                key = _norm_key(t)
                break
        if not key:
            continue
        cv = line.select(".copy-value")
        if cv:
            val = _clean_text(" ".join(x.get_text(" ", strip=True) for x in cv))
        else:
            v = line.select_one(".val")
            val = _clean_text(v.get_text(" ", strip=True)) if v else _clean_text(line.get_text(" ", strip=True))
        if "法定代表人" in key and not legal_person:
            a = line.select_one("a")
            if a:
                legal_person = _clean_text(a.get_text(" ", strip=True))
                _put_if_absent(kv, key, legal_person)
                continue
        _put_if_absent(kv, key, val)

    # 如果表格中没拿到法人，这里兜底
    if not legal_person:
        maybe_legal = kv.get("法定代表人")
        if maybe_legal:
            legal_person = maybe_legal

    return {
        "http_status": resp.status_code,
        "final_url": resp_url,
        "page_title": page_title,
        "blocked_reason": blocked_reason,
        "used_drissionpage": used_drission,
        "drission_error": drission_error,
        "html_len": len(html),
        "has_cominfo": has_cominfo,
        "has_contact": has_contact,
        "fields": kv,
        "legal_person": legal_person,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--keyno", default="", help="企业 KeyNo（单条模式）")
    ap.add_argument(
        "--from-exact",
        action="store_true",
        help="从 qcc_brand_qcc_top2_exact.json 提取 KeyNo 批量请求",
    )
    ap.add_argument(
        "--exact-file",
        default=os.path.join(os.path.dirname(BASE_DIR), "qcc_brand_qcc_top2_exact.json"),
        help="精确匹配文件路径（批量模式）",
    )
    ap.add_argument("--sleep", type=float, default=1.2, help="批量模式每次请求间隔秒数")
    ap.add_argument(
        "--out",
        default=os.path.join(os.path.dirname(BASE_DIR), "qcc_firm_detail_api_result.json"),
        help="输出文件路径",
    )
    ap.add_argument(
        "--save-html",
        action="store_true",
        help="保存 requests/drission 获取到的 html 供排查",
    )
    ap.add_argument(
        "--html-dir",
        default=os.path.join(os.path.dirname(BASE_DIR), "qcc_firm_html_debug"),
        help="HTML 保存目录（配合 --save-html）",
    )
    args = ap.parse_args()

    cookie = os.environ.get("QCC_COOKIE", DEFAULT_COOKIE).strip()

    session = requests.Session()

    if args.from_exact:
        with open(args.exact_file, "r", encoding="utf-8") as f:
            exact_data = json.load(f)

        key_nos: List[str] = []
        seen = set()
        for row in exact_data.get("results", []):
            for it in row.get("top2", []):
                kn = str(it.get("KeyNo") or "").strip()
                if kn and kn not in seen:
                    seen.add(kn)
                    key_nos.append(kn)

        batch_results = []
        for idx, key_no in enumerate(key_nos, start=1):
            firm_url = f"https://www.qcc.com/firm/{key_no}.html"
            print(f"[{idx}/{len(key_nos)}] {key_no}")
            item: Dict[str, Any] = {"keyNo": key_no, "firm_url": firm_url}
            try:
                item["firmBasicInfoHtml"] = extract_basic_info_from_firm_html(
                    session,
                    key_no,
                    cookie,
                    save_html=args.save_html,
                    html_dir=args.html_dir,
                )
            except Exception as e:
                item["error"] = str(e)
            batch_results.append(item)
            time.sleep(args.sleep)

        result = {
            "source_exact_file": os.path.abspath(args.exact_file),
            "total_keyno": len(key_nos),
            "results": batch_results,
        }
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"已写入: {args.out}")
        print(f"批量完成: {len(batch_results)} 条")
        return

    key_no = args.keyno.strip()
    if not key_no:
        raise ValueError("单条模式需要传 --keyno，或使用 --from-exact 批量模式")

    firm_url = f"https://www.qcc.com/firm/{key_no}.html"
    result = {
        "keyNo": key_no,
        "firm_url": firm_url,
        "firmBasicInfoHtml": extract_basic_info_from_firm_html(
            session,
            key_no,
            cookie,
            save_html=args.save_html,
            html_dir=args.html_dir,
        ),
    }

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f"已写入: {args.out}")
    print(f"firm_url: {firm_url}")
    print(f"firmBasicInfoHtml http={result['firmBasicInfoHtml']['http_status']}")


if __name__ == "__main__":
    main()

