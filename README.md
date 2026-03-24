# 企查查公司信息抓取 README

本项目用于：**从品牌/公司名单出发，在企查查检索主体，并抓取公司基本信息**。  
核心目标是尽量稳定地获取以下字段：企业名称、统一社会信用代码、法人、注册资本、状态、电话、邮箱、地址、经营范围等。

---

## 1. 项目文件与数据流

结合当前目录与项目根目录中的文件，完整链路如下：

1. **品牌名映射为工商主体**
   - 输入：`qcc_brand_to_company_map.json`
   - 作用：把品牌简称映射到企查查可检索的工商全称，并支持地址特例覆盖（如 `ECO互娱`）。

2. **批量 searchMulti 检索**
   - 脚本：`qcc_batch_brand_search.py`
   - 输出：`qcc_brand_qcc_top2.json`
   - 作用：按每个公司名调用 `searchMulti`，保留 top2 候选结果（含 `KeyNo`）。

3. **按 KeyNo 抓 firm 详情页并解析基本信息**
   - 脚本：`qcc_firm_detail_apis.py`
   - 输出：`qcc_firm_detail_api_result.json`
   - 作用：访问 `https://www.qcc.com/firm/{KeyNo}.html`，解析公司字段。

4. **早期调试与逆向验证**
   - 脚本：`02_逆向 header 加密.py`
   - 公共模块：`qcc_search_helpers.py`
   - 早期样例输出：`qcc_api_result.json`（示例里曾出现 `search_keynos_count=0`）。

---

## 2. 遇到的主要困难与解决办法

### 困难 A：`searchMulti` 返回异常（如 435 / 未知错误）

- **现象**
  - 能请求到接口，但业务状态异常，拿不到有效 `Result`，`qcc_api_result.json` 中出现 `search_keynos_count: 0`。
- **根因**
  - 请求头签名与浏览器不一致，常见于：
    - payload 被双重序列化（Python 先转字符串，JS 又 `JSON.stringify` 一次）。
    - `window.pid / window.tid` 取值不对或不是当前会话页面提取。
    - `Referer`、`x-pid`、签名字段不匹配。
- **解决**
  - 把签名逻辑抽到 `qcc_search_helpers.py`，统一处理：
    - 使用与浏览器一致的 JSON 序列化：`json.dumps(..., separators=(",", ":"), ensure_ascii=True)`。
    - 先访问搜索页解析 `window.pid` 和 `window.tid`。
    - 使用 `02_企查查_header加密逻辑.js` 计算动态签名头后再发请求。

---

### 困难 B：搜索结果里经常混入“分公司/工会/关联企业”

- **现象**
  - `qcc_brand_qcc_top2.json` 的 top2 中常见类似“XX分公司”“工会委员会”。
- **根因**
  - searchMulti 的命中逻辑不仅按公司名，还可能按股东、曾用名、历史股东等字段召回。
- **解决**
  - 通过映射表先收敛关键词（`qcc_brand_to_company_map.json`）。
  - 后续筛选时按“公司名精确匹配 + 排除分公司后缀”策略过滤（你之前已执行该思路）。
  - 遇到别名/旧名情况，利用 `address_overrides` 做地址定向覆盖。

---

### 困难 C：firm 页 HTTP 200，但 DOM 抓不到信息（壳页）

- **现象**
  - `qcc_firm_detail_api_result.json` 中可见：
    - `http_status: 200`
    - `blocked_reason: "blocked_login"`
    - `has_cominfo: false`, `has_contact: false`
  - 但页面“源代码”里实际有数据。
- **根因**
  - 详情页是前端框架渲染形态，直接解析可见 DOM 会拿到壳结构；关键数据在脚本变量 `window.__INITIAL_STATE__` 中。
- **解决（当前主方案）**
  - 在 `qcc_firm_detail_apis.py` 里**优先解析 `window.__INITIAL_STATE__`**：
    - 从 HTML 源码定位 `window.__INITIAL_STATE__ = {...}`。
    - 用大括号配对提取完整 JSON（避免正则截断）。
    - 从 `company.companyDetail` 抽取标准字段。
  - DOM 表格解析与 DrissionPage 保留为兜底，不再作为主路径。

> 当前效果：即使 `blocked_login` 且 `has_cominfo=false`，仍可从 `fields` 提取到企业名称、信用代码、法人、注册资本、经营范围等信息（见 `qcc_firm_detail_api_result.json`）。

---

## 3. 当前推荐抓取流程

### 第一步：维护映射表

编辑 `qcc_brand_to_company_map.json`：
- `brand_to_legal_name`：品牌 -> 工商主体名
- `address_overrides`：同品牌多主体时，按地址关键词覆盖

---

### 第二步：批量检索公司并拿 KeyNo

在 `企查查公司抓取逆向爬虫` 目录执行：

```powershell
& "C:/ProgramData/anaconda3/python.exe" "p:/Qcc_Reverse_Firm-Info_Crawler/qcc_batch_brand_search.py"
```

产物：`p:\25计设比赛\qcc_brand_qcc_top2.json`

---

### 第三步：按 KeyNo 抓公司基本信息

单条：

```powershell
& "C:/ProgramData/anaconda3/python.exe" "p:/Qcc_Reverse_Firm-Info_Crawler/qcc_firm_detail_apis.py" --keyno 57f1f9bdf8be4a9575357e5844268847 --save-html
```

批量（从精确筛选文件）：

```powershell
& "C:/ProgramData/anaconda3/python.exe" "p:/Qcc_Reverse_Firm-Info_Crawler/qcc_firm_detail_apis.py" --from-exact --save-html
```

产物：`p:\25计设比赛\qcc_firm_detail_api_result.json`

---

## 4. 关键实现要点（代码层）

- `qcc_search_helpers.py`
  - 统一封装：`fetch_pid_tid`、`build_signed_headers`、`post_search_multi`。
  - 保证签名入参与浏览器一致，减少 435/校验失败。

- `qcc_batch_brand_search.py`
  - 从映射表读取全称关键词，批量调用 searchMulti。
  - 结构化输出 top2 结果，保留 `KeyNo`、命中字段、信用代码、状态等。

- `qcc_firm_detail_apis.py`
  - 主路径：`window.__INITIAL_STATE__` -> `company.companyDetail`。
  - 兜底路径：DOM 解析（`cominfo-normal` / `contact-info`）和 DrissionPage。
  - 调试字段：`blocked_reason`、`html_len`、`has_cominfo`、`has_contact`、`used_drissionpage`。

---

## 5. 已验证结果（基于当前样例）

`qcc_firm_detail_api_result.json` 当前样例显示：
- 页面可能被判定为登录壳页（`blocked_login`）。
- 但 `fields` 仍成功提取到：
  - 企业名称
  - 统一社会信用代码
  - 法定代表人
  - 注册资本
  - 登记状态
  - 注册地址
  - 经营范围
  - 电话 / 邮箱
  - 行业与地区信息

这说明“解析源代码中的 `__INITIAL_STATE__`”是当前最稳妥方案。

---

## 6. 常见问题排查

- **`search_keynos_count=0` 或 `Status != 200`**
  - 优先检查 Cookie 是否过期、签名是否仍有效、`window.pid/tid` 是否从当前页面提取。

- **结果总是命中分公司**
  - 在后处理阶段加“主体名精确匹配 + 排除分公司关键词”规则。
  - 对歧义品牌补充 `address_overrides`。

- **详情页无 DOM 数据**
  - 先看是否有 `window.__INITIAL_STATE__`，有则直接解析该 JSON，不依赖渲染后 DOM。

---

## 7. 后续可优化方向

- 输出再标准化：增加英文固定 key（如 `company_name`、`credit_code`、`legal_person`）。
- 增加自动重试与 Cookie 轮换策略，提高批量稳定性。
- 增加“精确匹配评分”与冲突告警（同名多主体时自动提示人工确认）。

