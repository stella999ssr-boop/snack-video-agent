"""
蝉妈妈爆款视频搜索工具

三步走：
  1. 运行 login() → 弹出浏览器 → 手动扫码/密码登录蝉妈妈 → 关闭
  2. 运行 search("爆浆芝士年糕") → 自动搜索 → 返回视频列表
  3. 登录态保存在 ./browser_profile/ 目录，7天内有效

依赖: pip install playwright && playwright install chromium
"""

import json
import time
from pathlib import Path
from typing import Optional

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
except ImportError:
    raise ImportError("请先安装: pip install playwright && playwright install chromium")


# 蝉妈妈搜索页 URL
CHANMAMA_SEARCH_URL = "https://www.chanmama.com/video/search"
# 浏览器 profile 保存位置
PROFILE_DIR = Path(__file__).resolve().parent / "browser_profile"


class ChanmamaTool:
    """蝉妈妈视频搜索工具"""

    def __init__(self, profile_dir: str = ""):
        self.profile_dir = str(Path(profile_dir) if profile_dir else PROFILE_DIR)
        Path(self.profile_dir).mkdir(parents=True, exist_ok=True)

    # ─── 第一步：手动登录（只做一次）─────────────────

    def login(self):
        """打开浏览器，等你在蝉妈妈完成登录后关闭窗口即可"""
        print("=" * 60)
        print("正在启动浏览器...")
        print("请在浏览器中登录蝉妈妈（扫码或密码）")
        print("登录成功后，关闭浏览器窗口即可")
        print("=" * 60)

        with sync_playwright() as p:
            # 用系统自带的 Edge 浏览器（国内免翻墙下载）
            browser = p.chromium.launch_persistent_context(
                user_data_dir=self.profile_dir,
                channel="msedge",   # 使用 Microsoft Edge
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
                viewport={"width": 1400, "height": 900},
            )
            page = browser.new_page()
            page.goto("https://www.chanmama.com/login", wait_until="domcontentloaded")

            print("\n浏览器已打开，请在浏览器窗口中完成登录操作。")
            print("完成后按 Ctrl+C 或直接关闭浏览器窗口。\n")

            try:
                # 等待用户手动操作（最长等 10 分钟）
                page.wait_for_url("https://www.chanmama.com/**", timeout=600_000)
            except PwTimeout:
                pass
            finally:
                # 保存 storage state
                browser.storage_state(path=f"{self.profile_dir}/state.json")
                browser.close()

        print("登录信息已保存。现在可以运行 search() 搜索视频了。")

    # ─── 第二步：搜索视频 ──────────────────────────

    def search(
        self,
        keyword: str,
        max_results: int = 20,
        min_likes: int = 1000,
        days: int = 30,
    ) -> list[dict]:
        """
        搜索蝉妈妈视频榜单。

        Args:
            keyword: 搜索关键词，如 "爆浆芝士年糕"
            max_results: 最多返回多少条
            min_likes: 最低点赞数过滤
            days: 搜索最近多少天的视频

        Returns:
            [
                {
                    "title": "视频标题",
                    "url": "抖音视频链接",
                    "likes": 52000,
                    "comments": 1200,
                    "shares": 3400,
                    "duration": 18,
                    "publish_time": "2026-05-25",
                    "author": "博主名",
                    "author_followers": 150000,
                },
                ...
            ]
        """
        print(f"搜索关键词: {keyword}")
        print(f"条件: 点赞≥{min_likes}, 最近{days}天, 最多{max_results}条")

        results = []

        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=self.profile_dir,
                channel="msedge",
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
                viewport={"width": 1400, "height": 900},
            )
            page = browser.new_page()

            # ── 拦截所有 JSON 响应 ──
            api_responses = []

            def on_response(response):
                content_type = response.headers.get("content-type", "")
                if "application/json" not in content_type:
                    return
                try:
                    body = response.json()
                    api_responses.append({"url": response.url, "body": body})
                except Exception:
                    pass

            page.on("response", on_response)

            # ── 步骤 1：打开首页 ──
            print("打开蝉妈妈首页...")
            page.goto("https://www.chanmama.com", wait_until="domcontentloaded", timeout=30000)
            time.sleep(5)
            print(f"首页标题: {page.title()}")

            # ── 步骤 2：点"找视频" ──
            try:
                video_tab = page.wait_for_selector("span.search-label:has-text('找视频')", timeout=5000)
                if video_tab:
                    video_tab.click()
                    print("已切换到'找视频'")
                    time.sleep(2)
            except Exception:
                print("未找到'找视频'标签")

            # ── 步骤 3：用 JS 找到真正的输入框并填入关键词 ──
            # 蝉妈妈可能用 Element UI 的 el-input，实际 input 的 class 是 el-input__inner
            typed = page.evaluate(f"""keyword => {{
                // 尝试多种选择器找到搜索输入框
                const selectors = [
                    '.agg-search-box input[type="text"]',
                    '.agg-search-box .el-input__inner',
                    '.search-content input',
                    '.dy-search-slide-wrapper input',
                    'input[placeholder*="搜索"]',
                    'input[placeholder*="关键词"]',
                ];
                let input = null;
                for (const sel of selectors) {{
                    const el = document.querySelector(sel);
                    if (el && el.offsetWidth > 0) {{
                        input = el;
                        break;
                    }}
                }}
                if (!input) {{
                    // 最后尝试：找 .agg-search-box 下所有可见 input
                    const box = document.querySelector('.agg-search-box');
                    if (box) {{
                        const inputs = box.querySelectorAll('input');
                        for (const el of inputs) {{
                            if (el.offsetWidth > 0 && el.type !== 'checkbox' && el.type !== 'hidden') {{
                                input = el;
                                break;
                            }}
                        }}
                    }}
                }}
                if (input) {{
                    input.focus();
                    input.value = '';
                    // 模拟逐字输入（触发 Vue/React 的 input 事件）
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    nativeInputValueSetter.call(input, keyword);
                    input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                    return 'found: ' + (input.className || input.tagName);
                }}
                return 'not_found';
            }}""", keyword)
            print(f"JS 查找输入框结果: {typed}")

            if typed.startswith("found"):
                time.sleep(1)
                page.keyboard.press("Enter")
                print("已提交搜索，等待结果...")
                time.sleep(8)
            else:
                # 如果 JS 也找不到，用键盘直接输入
                print("JS 未找到输入框，尝试键盘输入...")
                try:
                    search_area = page.wait_for_selector(".agg-search-box", timeout=3000)
                    if search_area:
                        search_area.click()
                        time.sleep(1)
                        # 全选清空再输入
                        page.keyboard.press("Control+a")
                        page.keyboard.type(keyword, delay=80)
                        time.sleep(1)
                        page.keyboard.press("Enter")
                        print("键盘输入完成，等待结果...")
                        time.sleep(8)
                except Exception as e:
                    print(f"键盘输入也失败: {e}")

            print(f"最终页面 URL: {page.url}")
            print(f"最终页面标题: {page.title()}")

            # ── 步骤 4：如果页面没有跳转到搜索结果，尝试直接调 API ──
            if "404" in page.title() or page.url == "https://www.chanmama.com/":
                print("页面未跳转到搜索结果，尝试直接调用搜索 API...")
                # 从浏览器获取 cookie
                cookies = page.context.cookies()
                cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)

                # 尝试蝉妈妈搜索 API（需要 bearer token）
                # 先尝试从 localStorage 获取 token
                token = page.evaluate("() => localStorage.getItem('token') || localStorage.getItem('access_token') || ''")
                print(f"localStorage token: {token[:20] if token else '无'}...")

                # 尝试从页面请求头中获取 authorization
                auth_header = ""
                for resp in api_responses:
                    # 有些 API 响应可能包含 token 信息
                    pass

                # 用 playwright 发带 cookie 的 API 请求
                api_urls_to_try = [
                    f"https://api-service.chanmama.com/v1/video/search?keyword={keyword}&page=1&size=20",
                    f"https://api-service.chanmama.com/v1/search/video?keyword={keyword}&page=1&size=20",
                    f"https://api-service.chanmama.com/v1/material/search?keyword={keyword}&page=1&size=20&type=video",
                ]
                for api_url in api_urls_to_try:
                    try:
                        resp = page.evaluate(f"""async url => {{
                            const res = await fetch(url, {{
                                headers: {{ 'Content-Type': 'application/json' }},
                                credentials: 'include',
                            }});
                            const text = await res.text();
                            return {{ status: res.status, text: text.slice(0, 500) }};
                        }}""", api_url)
                        print(f"API 尝试 {api_url}: status={resp['status']}")
                        if resp['status'] == 200 and len(resp['text']) > 50:
                            print(f"  响应: {resp['text'][:200]}")
                            try:
                                data = json.loads(resp['text'])
                                videos = self._extract_videos(data, min_likes)
                                results.extend(videos)
                            except Exception:
                                pass
                    except Exception as e:
                        print(f"  API 调用失败: {e}")

            # ── 步骤 5：从拦截到的响应中提取数据 ──
            print(f"共拦截到 {len(api_responses)} 个 JSON 响应")

            # 筛选包含视频数据的响应（打印前几个 URL 帮助判断）
            video_related = []
            for resp in api_responses:
                url = resp["url"]
                if any(kw in url for kw in ["search", "video", "material", "hot", "rank", "aweme", "jx/getToday"]):
                    video_related.append(resp)

            print(f"其中视频相关响应: {len(video_related)} 个")
            for resp in video_related:
                print(f"  {resp['url'][:150]}")
                videos = self._extract_videos(resp["body"], min_likes)
                results.extend(videos)

            # 如果视频相关没数据，再遍历所有响应
            if not results:
                print("视频相关 API 无数据，遍历全部响应...")
                for resp in api_responses:
                    videos = self._extract_videos(resp["body"], min_likes)
                    results.extend(videos)

            if not results:
                print("API 无数据，尝试 DOM 解析...")
                results = self._parse_dom(page, keyword, min_likes)

            browser.close()

        # 去重 + 排序 + 截断
        seen = set()
        unique = []
        for v in sorted(results, key=lambda x: x.get("likes", 0), reverse=True):
            if v["url"] not in seen:
                seen.add(v["url"])
                unique.append(v)

        output = unique[:max_results]
        print(f"找到 {len(output)} 条符合条件的视频")
        return output

    # ─── 数据提取 ──────────────────────────────────

    def _extract_videos(self, data: dict, min_likes: int) -> list[dict]:
        """从蝉妈妈 API 响应中递归提取视频列表"""
        results = []

        def walk(obj, depth=0):
            if depth > 10:
                return
            if isinstance(obj, dict):
                # 判断是否为视频条目
                if any(k in obj for k in ["video_id", "aweme_id", "item_id"]):
                    likes = self._get_int(obj, ["like_count", "digg_count", "likes"])
                    if likes >= min_likes:
                        results.append(self._normalize_video(obj, likes))
                for v in obj.values():
                    walk(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item, depth + 1)

        walk(data)
        return results

    def _parse_dom(self, page, keyword: str, min_likes: int) -> list[dict]:
        """DOM 降级方案：解析页面元素"""
        results = []
        # 等待列表容器出现
        selectors = [
            ".video-list-item",
            ".search-result-item",
            "[class*='video']",
            "tr[class*='item']",
        ]

        items = []
        for sel in selectors:
            try:
                page.wait_for_selector(sel, timeout=5000)
                items = page.query_selector_all(sel)
                if items:
                    break
            except Exception:
                continue

        if not items:
            print("未找到视频列表元素。可能需要更新选择器。")
            # 打印页面标题帮助调试
            print(f"页面标题: {page.title()}")
            return results

        for item in items[:50]:
            try:
                title_el = item.query_selector("a[class*='title'], .title, [class*='name']")
                title = title_el.inner_text() if title_el else ""

                url_el = item.query_selector("a[href*='douyin.com'], a[href*='iesdouyin']")
                url = url_el.get_attribute("href") if url_el else ""

                likes = 0
                likes_el = item.query_selector("[class*='like'], [class*='count']")
                if likes_el:
                    likes_text = likes_el.inner_text()
                    likes = self._parse_number(likes_text)

                if likes >= min_likes:
                    results.append({
                        "title": title.strip(),
                        "url": url.strip(),
                        "likes": likes,
                        "comments": 0,
                        "shares": 0,
                        "duration": 0,
                        "publish_time": "",
                        "author": "",
                        "author_followers": 0,
                    })
            except Exception:
                continue

        return results

    def _normalize_video(self, obj: dict, likes: int) -> dict:
        """统一字段名"""
        return {
            "title": str(obj.get("title") or obj.get("desc") or ""),
            "url": str(obj.get("video_url") or obj.get("share_url") or obj.get("url") or ""),
            "likes": likes,
            "comments": self._get_int(obj, ["comment_count", "comments"]),
            "shares": self._get_int(obj, ["share_count", "shares"]),
            "duration": self._get_int(obj, ["duration", "video_duration"]),
            "publish_time": str(obj.get("publish_time") or obj.get("create_time") or ""),
            "author": str(obj.get("author") or obj.get("nickname") or ""),
            "author_followers": self._get_int(obj, ["follower_count", "followers"]),
        }

    @staticmethod
    def _get_int(obj: dict, keys: list[str]) -> int:
        for k in keys:
            v = obj.get(k)
            if v is not None:
                try:
                    return int(v)
                except (ValueError, TypeError):
                    pass
        return 0

    @staticmethod
    def _parse_number(text: str) -> int:
        """'5.2万' → 52000"""
        text = text.strip().replace(",", "").replace(" ", "")
        try:
            if "万" in text:
                return int(float(text.replace("万", "")) * 10000)
            return int(float(text))
        except ValueError:
            return 0


    # ─── 抓包模式：手动操作，自动记录 API ─────────

    def sniff(self):
        """打开浏览器，你手动搜索，我抓取所有 API 请求"""
        print("=" * 60)
        print("抓包模式")
        print("1. 浏览器打开后，请在搜索框手动输入关键词搜索")
        print("2. 操作完成后，按 Enter 键结束")
        print("=" * 60)

        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=self.profile_dir,
                channel="msedge",
                headless=False,
                args=["--disable-blink-features=AutomationControlled"],
                viewport={"width": 1400, "height": 900},
            )
            page = browser.new_page()

            all_requests = []
            all_responses = []

            def on_request(request):
                url = request.url
                if any(kw in url for kw in ["api-service", "api", "jx-api"]):
                    all_requests.append({
                        "url": url,
                        "method": request.method,
                        "post_data": str(request.post_data)[:300] if request.post_data else "",
                    })

            def on_response(response):
                url = response.url
                if any(kw in url for kw in ["api-service", "api", "jx-api"]):
                    content_type = response.headers.get("content-type", "")
                    body_preview = ""
                    if "application/json" in content_type:
                        try:
                            body = response.json()
                            body_preview = json.dumps(body, ensure_ascii=False)[:500]
                        except Exception:
                            body_preview = "(非 JSON)"
                    all_responses.append({
                        "url": url,
                        "status": response.status,
                        "body_preview": body_preview,
                    })

            page.on("request", on_request)
            page.on("response", on_response)

            page.goto("https://www.chanmama.com", wait_until="domcontentloaded", timeout=30000)
            print("\n浏览器已打开，请手动操作搜索。")
            print("操作完成后，回到终端按 Ctrl+C 结束抓包。\n")

            try:
                time.sleep(600)  # 等10分钟，用户按 Ctrl+C 中断
            except KeyboardInterrupt:
                print("\n收到中断信号，正在分析抓包数据...\n")

            try:
                browser.close()
            except Exception:
                pass

        # 分析结果
        print("\n" + "=" * 60)
        print(f"共捕获 {len(all_requests)} 个 API 请求, {len(all_responses)} 个 API 响应")
        print("=" * 60)

        # 按 URL 分组去重显示
        seen_urls = set()
        print("\n--- API 请求列表（去重）---")
        for req in all_requests:
            base_url = req["url"].split("?")[0]
            if base_url not in seen_urls:
                seen_urls.add(base_url)
                print(f"  {req['method']} {base_url}")
                if req["post_data"]:
                    print(f"    Body: {req['post_data']}")

        print("\n--- API 响应列表 ---")
        for resp in all_responses:
            print(f"  [{resp['status']}] {resp['url'][:150]}")
            if resp["body_preview"]:
                print(f"    {resp['body_preview'][:300]}")
            print()

        # 尝试提取视频数据
        print("--- 尝试提取视频数据 ---")
        results = []
        for resp in all_responses:
            if resp["body_preview"]:
                try:
                    data = json.loads(resp["body_preview"]) if isinstance(resp["body_preview"], str) else resp["body_preview"]
                    videos = self._extract_videos(data, 0)
                    if videos:
                        print(f"从 {resp['url'][:120]} 提取到 {len(videos)} 条视频")
                        results.extend(videos)
                except Exception:
                    pass

        print(f"\n共提取 {len(results)} 条视频")
        for v in results[:5]:
            print(f"  {v['title'][:50]} | 赞:{v['likes']} | {v['author']}")

        return results


# ═══════════════════════════════════════════════════
# 命令行入口
# ═══════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    tool = ChanmamaTool()

    if len(sys.argv) < 2:
        print("用法:")
        print("  python chanmama.py login              ← 首次登录（打开浏览器）")
        print("  python chanmama.py search \"爆浆芝士年糕\" ← 搜索视频")
        print("  python chanmama.py sniff              ← 抓包模式（手动操作）")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "login":
        tool.login()

    elif cmd == "sniff":
        results = tool.sniff()
        print(json.dumps(results, ensure_ascii=False, indent=2))

    elif cmd == "search":
        keyword = sys.argv[2] if len(sys.argv) > 2 else "零食"
        results = tool.search(keyword=keyword, max_results=20)
        print(json.dumps(results, ensure_ascii=False, indent=2))
