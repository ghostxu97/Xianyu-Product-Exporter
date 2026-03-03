#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

LogFn = Callable[[str], None]


def clean_name(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value).strip()
    value = re.sub(r"\s+", " ", value)
    return value[:80] or "untitled"


def clean_segment(value: str, max_len: int = 40) -> str:
    value = re.sub(r"[\\/:*?\"<>|]+", "_", value).strip()
    value = re.sub(r"\s+", "-", value)
    value = value.strip("-_")
    if not value:
        return "unknown"
    return value[:max_len]


def parse_price(text: str) -> str:
    text = "".join(text.split())
    match = re.search(r"¥\s*([0-9]+(?:\.[0-9]+)?)", text)
    return match.group(1) if match else ""


def item_id_from_href(href: str) -> str:
    query = parse_qs(urlparse(href).query)
    return query.get("id", [""])[0] or "unknown"


def split_keywords(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[,\n，]+", raw)
    return [p.strip().lower() for p in parts if p.strip()]


def match_filters(text: str, include: list[str], exclude: list[str]) -> bool:
    lowered = text.lower()
    if include and not any(k in lowered for k in include):
        return False
    if exclude and any(k in lowered for k in exclude):
        return False
    return True


def cookie_token(cookie: str) -> str:
    m = re.search(r"(?:^|;\s*)_m_h5_tk=([^;]+)", cookie)
    if not m:
        return ""
    return m.group(1).split("_")[0]


def to_abs_image_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return f"https:{url}"
    if url.startswith("http://"):
        return f"https://{url[7:]}"
    return url


def user_id_from_personal_url(personal_url: str) -> str:
    parsed = urlparse(personal_url)
    user_id = parse_qs(parsed.query).get("userId", [""])[0]
    return user_id.strip()


def fetch_personal_html(personal_url: str, cookie: str, html_path: Path) -> Path:
    headers = {
        "cookie": cookie,
        "referer": "https://www.goofish.com/",
        "user-agent": "Mozilla/5.0",
    }
    resp = requests.get(personal_url, headers=headers, timeout=30)
    resp.raise_for_status()
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text(resp.text, encoding="utf-8")
    return html_path


def request_mtop(
    session: requests.Session,
    cookie: str,
    api: str,
    data_obj: dict,
    referer: str,
    v: str = "1.0",
) -> dict:
    token = cookie_token(cookie)
    if not token:
        raise RuntimeError("cookie 中缺少 _m_h5_tk，无法生成签名。")
    app_key = "34839810"
    data = json.dumps(data_obj, ensure_ascii=False, separators=(",", ":"))
    ts = str(int(time.time() * 1000))
    sign = hashlib.md5(f"{token}&{ts}&{app_key}&{data}".encode("utf-8")).hexdigest()
    params = {
        "jsv": "2.7.2",
        "appKey": app_key,
        "t": ts,
        "sign": sign,
        "api": api,
        "v": v,
        "type": "originaljson",
        "dataType": "json",
        "timeout": "20000",
    }
    headers = {"cookie": cookie, "referer": referer, "user-agent": "Mozilla/5.0"}
    resp = session.post(
        f"https://h5api.m.goofish.com/h5/{api}/{v}/",
        params=params,
        data={"data": data},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()
    payload = resp.json()
    ret = payload.get("ret") or []
    if not ret or not str(ret[0]).startswith("SUCCESS"):
        raise RuntimeError(f"{api} 调用失败: {ret}")
    return payload.get("data", {})


def fetch_user_nick(session: requests.Session, cookie: str, user_id: str, referer: str) -> str:
    data = request_mtop(
        session=session,
        cookie=cookie,
        api="mtop.idle.web.user.page.head",
        data_obj={"self": False, "userId": user_id},
        referer=referer,
        v="1.0",
    )
    # 接口字段在不同场景下可能不同，做兜底
    for path in [
        ("nick",),
        ("userInfo", "nick"),
        ("userInfoDO", "nick"),
        ("baseDO", "nick"),
        ("baseInfo", "nick"),
        ("headDO", "nick"),
        ("module", "base", "displayName"),
        ("module", "base", "displayNick"),
        ("baseInfo", "displayName"),
    ]:
        cur = data
        ok = True
        for key in path:
            if not isinstance(cur, dict) or key not in cur:
                ok = False
                break
            cur = cur[key]
        if ok and isinstance(cur, str) and cur.strip():
            return cur.strip()
    return ""


def build_default_output_dir(
    personal_url: str,
    cookie: str,
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    base_dir: Path | None = None,
) -> Path:
    include_keywords = include_keywords or []
    exclude_keywords = exclude_keywords or []
    base_dir = base_dir or Path(__file__).resolve().parent

    user_id = user_id_from_personal_url(personal_url) or "unknown"
    nick = ""
    try:
        session = requests.Session()
        nick = fetch_user_nick(session, cookie, user_id, personal_url)
    except Exception:
        nick = ""
    nick_part = clean_segment(nick or "unknown")
    user_part = clean_segment(user_id, max_len=24)
    ts_part = datetime.now().strftime("%Y%m%d_%H%M%S")

    include_part = "inc-" + clean_segment("-".join(include_keywords), max_len=40) if include_keywords else "inc-all"
    exclude_part = "exc-" + clean_segment("-".join(exclude_keywords), max_len=40) if exclude_keywords else "exc-none"

    folder_name = f"{nick_part}_{user_part}_{ts_part}_{include_part}_{exclude_part}"
    return (base_dir / folder_name).resolve()


def fetch_user_items(
    session: requests.Session, cookie: str, personal_url: str, log: LogFn | None = None
) -> list[dict]:
    user_id = user_id_from_personal_url(personal_url)
    if not user_id:
        raise RuntimeError("personal-url 中缺少 userId 参数。")

    all_items: list[dict] = []
    page_number = 1
    next_page_model = None
    next_page_num = None

    while True:
        data_obj = {
            "needGroupInfo": page_number == 1,
            "pageNumber": page_number,
            "userId": user_id,
            "pageSize": 20,
        }
        if next_page_model:
            data_obj["nextPageModel"] = next_page_model
        if next_page_num:
            data_obj["nextPageNum"] = next_page_num

        try:
            data = request_mtop(
                session=session,
                cookie=cookie,
                api="mtop.idle.web.xyh.item.list",
                data_obj=data_obj,
                referer=personal_url,
                v="1.0",
            )
        except RuntimeError as e:
            msg = str(e)
            if "FAIL_BIZ_FORBIDDEN" in msg:
                _log(log, f"分页触发平台上限，停止继续翻页。当前已抓取 {len(all_items)} 条商品候选。")
                break
            raise

        for card in data.get("cardList") or []:
            card_data = card.get("cardData") or {}
            detail_params = card_data.get("detailParams") or {}
            item_id = str(detail_params.get("itemId") or "").strip()
            if not item_id:
                continue
            title = str(card_data.get("title") or detail_params.get("title") or "").strip()
            current_price = str((card_data.get("priceInfo") or {}).get("price") or detail_params.get("soldPrice") or "").strip()
            all_items.append(
                {
                    "item_id": item_id,
                    "title": title,
                    "current_price": current_price,
                    "item_url": f"https://www.goofish.com/item?id={item_id}",
                }
            )

        if not data.get("nextPage"):
            break
        page_number += 1
        next_page_model = data.get("nextPageModel")
        next_page_num = data.get("nextPageNum")

    # de-dup keep first
    seen: set[str] = set()
    dedup: list[dict] = []
    for item in all_items:
        iid = item["item_id"]
        if iid in seen:
            continue
        seen.add(iid)
        dedup.append(item)
    return dedup


def request_detail(session: requests.Session, cookie: str, item_id: str) -> dict:
    return request_mtop(
        session=session,
        cookie=cookie,
        api="mtop.taobao.idle.pc.detail",
        data_obj={"itemId": item_id},
        referer=f"https://www.goofish.com/item?id={item_id}",
        v="1.0",
    )


def download_jpg(session: requests.Session, image_url: str, out_path: Path) -> bool:
    if not image_url:
        return False
    primary = to_abs_image_url(image_url)
    urls = [f"{primary}?x-oss-process=image/format,jpg", primary]
    headers = {"referer": "https://www.goofish.com/", "user-agent": "Mozilla/5.0"}

    for url in urls:
        try:
            resp = session.get(url, timeout=20, headers=headers)
            resp.raise_for_status()
            with Image.open(io.BytesIO(resp.content)) as img:
                img.convert("RGB").save(out_path, format="JPEG", quality=92)
            return True
        except Exception:
            continue
    return False


def _log(log: LogFn | None, message: str) -> None:
    if log:
        log(message)
    else:
        print(message, flush=True)


def export_products(
    html_path: Path,
    output_dir: Path,
    cookie: str | None = None,
    max_items: int = 0,
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    log: LogFn | None = None,
) -> dict:
    include_keywords = include_keywords or []
    exclude_keywords = exclude_keywords or []

    html_text = html_path.read_text(encoding="utf-8", errors="ignore")
    soup = BeautifulSoup(html_text, "html.parser")
    output_dir.mkdir(parents=True, exist_ok=True)
    fail_log = output_dir / "_detail_fail.log"
    if fail_log.exists():
        fail_log.unlink()

    seen: set[str] = set()
    exported = 0
    saved_image_count = 0
    skipped_by_filter = 0
    detail_fail_count = 0
    session = requests.Session()

    anchors = soup.select('a[href*="goofish.com/item?id="]')
    total = len(anchors)
    _log(log, f"离线 HTML 商品候选数: {total}")

    for idx_anchor, anchor in enumerate(anchors, start=1):
        href = anchor.get("href", "")
        item_id = item_id_from_href(href)
        if not item_id or item_id in seen:
            continue
        seen.add(item_id)

        title_wrap = anchor.select_one('[class*="row1-wrap-title"]')
        title = ""
        if title_wrap is not None:
            title = title_wrap.get("title", "").strip() or title_wrap.get_text(" ", strip=True)
        if not title:
            title = anchor.get_text(" ", strip=True)[:120]

        current_wrap = anchor.select_one('[class*="price-wrap"]')
        current_price = parse_price(current_wrap.get_text(" ", strip=True) if current_wrap else "")
        original_price = ""
        for n in anchor.select('[class*="price-desc"] [class*="text"]'):
            candidate = parse_price(n.get("title", "").strip() or n.get_text(" ", strip=True))
            if candidate:
                original_price = candidate
                break

        description = title
        image_urls: list[str] = []

        if cookie:
            try:
                detail = request_detail(session, cookie, item_id)
                item = detail.get("itemDO", {})
                title = str(item.get("title") or title).strip()
                description = str(item.get("desc") or title).strip()
                current_price = str(item.get("soldPrice") or current_price).strip()
                original_price = str(item.get("originalPrice") or original_price).strip()
                for image_info in item.get("imageInfos") or []:
                    if isinstance(image_info, dict):
                        u = to_abs_image_url(str(image_info.get("url") or ""))
                        if u:
                            image_urls.append(u)
            except Exception as e:
                detail_fail_count += 1
                fail_log.open("a", encoding="utf-8").write(
                    f"{item_id}\t{href}\t{type(e).__name__}: {e}\n"
                )

        filter_text = f"{title}\n{description}"
        if not match_filters(filter_text, include_keywords, exclude_keywords):
            skipped_by_filter += 1
            continue

        if max_items > 0 and exported >= max_items:
            break

        _log(log, f"[{exported + 1}] 导出商品 {item_id} ({idx_anchor}/{total})")

        folder = output_dir / f"{exported + 1:04d}-{clean_name(title)}"
        folder.mkdir(parents=True, exist_ok=True)
        for old_img in folder.glob("image_*"):
            if old_img.is_file():
                old_img.unlink()

        local_images: list[str] = []
        if image_urls:
            for idx, image_url in enumerate(image_urls, start=1):
                name = f"image_{idx:02d}.jpg"
                if download_jpg(session, image_url, folder / name):
                    local_images.append(name)
                    saved_image_count += 1
        else:
            cover = anchor.select_one('[class*="feeds-image-container"] img')
            if cover is not None:
                image_url = cover.get("src", "").strip()
                if image_url.startswith("./"):
                    image_url = image_url[2:]
                if image_url and not image_url.startswith(("http://", "https://")):
                    src = (html_path.parent / image_url).resolve()
                    if src.exists():
                        name = "image_01.jpg"
                        try:
                            with Image.open(src) as img:
                                img.convert("RGB").save(folder / name, format="JPEG", quality=92)
                            local_images.append(name)
                            image_urls.append(image_url)
                            saved_image_count += 1
                        except Exception:
                            ext = src.suffix or ".img"
                            raw_name = f"image_01{ext}"
                            shutil.copy2(src, folder / raw_name)
                            local_images.append(raw_name)
                            image_urls.append(image_url)
                            saved_image_count += 1

        record = {
            "item_id": item_id,
            "title": title,
            "description": description,
            "current_price": current_price,
            "original_price": original_price,
            "item_url": href,
            "images_source": image_urls,
            "images_local": local_images,
        }
        (folder / "product.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (folder / "product.txt").write_text(
            "\n".join(
                [
                    f"商品ID: {item_id}",
                    f"商品介绍: {description}",
                    f"商品现价: {current_price}",
                    f"商品原价: {original_price}",
                    f"商品链接: {href}",
                    "商品图片(源):",
                    *[f"  - {u}" for u in image_urls],
                    "商品图片(本地):",
                    *[f"  - {p}" for p in local_images],
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        exported += 1

    if detail_fail_count:
        _log(log, f"详情接口失败: {detail_fail_count} 个，详见 {fail_log}")

    summary = {
        "exported": exported,
        "images_saved": saved_image_count,
        "candidates": total,
        "skipped_by_filter": skipped_by_filter,
        "detail_fail_count": detail_fail_count,
    }
    _log(
        log,
        f"导出完成: {exported} 个商品文件夹, 共保存 {saved_image_count} 张图片, "
        f"过滤跳过 {skipped_by_filter} 个。",
    )
    return summary


def export_from_online(
    personal_url: str,
    output_dir: Path,
    cookie: str,
    max_items: int = 0,
    include_keywords: list[str] | None = None,
    exclude_keywords: list[str] | None = None,
    log: LogFn | None = None,
) -> dict:
    if not personal_url.strip():
        raise RuntimeError("缺少 personal_url。")
    if not cookie.strip():
        raise RuntimeError("缺少 cookies。")
    include_keywords = include_keywords or []
    exclude_keywords = exclude_keywords or []
    output_dir.mkdir(parents=True, exist_ok=True)
    fail_log = output_dir / "_detail_fail.log"
    if fail_log.exists():
        fail_log.unlink()

    source_html = output_dir / "_source" / "personal.html"
    try:
        html_path = fetch_personal_html(personal_url, cookie, source_html)
        _log(log, f"主页HTML已获取: {html_path}")
    except Exception as e:
        _log(log, f"主页HTML获取失败(不中断): {type(e).__name__}: {e}")

    session = requests.Session()
    items = fetch_user_items(session, cookie, personal_url, log=log)
    total = len(items)
    _log(log, f"在线商品候选数: {total}")

    exported = 0
    saved_image_count = 0
    skipped_by_filter = 0
    detail_fail_count = 0
    filtered_items: list[dict] = []

    _log(log, "开始预筛选：先遍历商品并应用关键词过滤...")
    for idx, base in enumerate(items, start=1):
        item_id = base["item_id"]
        title = base.get("title", "")
        description = title
        current_price = base.get("current_price", "")
        original_price = ""
        item_url = base.get("item_url", f"https://www.goofish.com/item?id={item_id}")
        image_urls: list[str] = []

        try:
            detail = request_detail(session, cookie, item_id)
            item = detail.get("itemDO", {})
            title = str(item.get("title") or title).strip()
            description = str(item.get("desc") or title).strip()
            current_price = str(item.get("soldPrice") or current_price).strip()
            original_price = str(item.get("originalPrice") or original_price).strip()
            for image_info in item.get("imageInfos") or []:
                if isinstance(image_info, dict):
                    u = to_abs_image_url(str(image_info.get("url") or ""))
                    if u:
                        image_urls.append(u)
        except Exception as e:
            detail_fail_count += 1
            fail_log.open("a", encoding="utf-8").write(
                f"{item_id}\t{item_url}\t{type(e).__name__}: {e}\n"
            )

        display_name = title or item_id
        if not match_filters(f"{title}\n{description}", include_keywords, exclude_keywords):
            skipped_by_filter += 1
            _log(log, f"{idx}/{total} 跳过：{display_name}")
            continue

        _log(log, f"{idx}/{total} 命中：{display_name}")
        filtered_items.append(
            {
                "item_id": item_id,
                "title": title,
                "description": description,
                "current_price": current_price,
                "original_price": original_price,
                "item_url": item_url,
                "image_urls": image_urls,
            }
        )
        if idx % 20 == 0:
            _log(log, f"预筛选进度: {idx}/{total}，当前命中 {len(filtered_items)}")

    filtered_total = len(filtered_items)
    export_items = filtered_items[:max_items] if max_items > 0 else filtered_items
    final_total = len(export_items)
    _log(log, f"预筛选完成：命中 {filtered_total} 个，实际将导出 {final_total} 个。")

    for out_idx, info in enumerate(export_items, start=1):
        item_id = info["item_id"]
        title = info["title"]
        description = info["description"]
        current_price = info["current_price"]
        original_price = info["original_price"]
        item_url = info["item_url"]
        image_urls = info["image_urls"]

        _log(log, f"导出商品 {out_idx}/{final_total}：{item_id}")
        folder = output_dir / f"{out_idx:04d}-{clean_name(title)}"
        folder.mkdir(parents=True, exist_ok=True)
        for old_img in folder.glob("image_*"):
            if old_img.is_file():
                old_img.unlink()

        local_images: list[str] = []
        if image_urls:
            for i, image_url in enumerate(image_urls, start=1):
                name = f"image_{i:02d}.jpg"
                if download_jpg(session, image_url, folder / name):
                    local_images.append(name)
                    saved_image_count += 1

        record = {
            "item_id": item_id,
            "title": title,
            "description": description,
            "current_price": current_price,
            "original_price": original_price,
            "item_url": item_url,
            "images_source": image_urls,
            "images_local": local_images,
        }
        (folder / "product.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (folder / "product.txt").write_text(
            "\n".join(
                [
                    f"商品ID: {item_id}",
                    f"商品介绍: {description}",
                    f"商品现价: {current_price}",
                    f"商品原价: {original_price}",
                    f"商品链接: {item_url}",
                    "商品图片(源):",
                    *[f"  - {u}" for u in image_urls],
                    "商品图片(本地):",
                    *[f"  - {p}" for p in local_images],
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        exported = out_idx

    if detail_fail_count:
        _log(log, f"详情接口失败: {detail_fail_count} 个，详见 {fail_log}")
    summary = {
        "exported": exported,
        "images_saved": saved_image_count,
        "candidates": total,
        "filtered_total": filtered_total,
        "skipped_by_filter": skipped_by_filter,
        "detail_fail_count": detail_fail_count,
    }
    _log(
        log,
        f"导出完成: {exported} 个商品文件夹, 共保存 {saved_image_count} 张图片, "
        f"过滤跳过 {skipped_by_filter} 个。",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Export products from Goofish personal URL into local folders."
    )
    parser.add_argument("--personal-url", required=True, help="闲鱼个人主页 URL。")
    parser.add_argument("--out", default="", help="输出目录。为空时自动按规则生成。")
    parser.add_argument("--cookie", default="", help="cookies 字符串。")
    parser.add_argument("--cookie-file", default="", help="cookies 文件路径。")
    parser.add_argument("--include-keywords", default="", help="包含关键词过滤，逗号分隔。")
    parser.add_argument("--exclude-keywords", default="", help="排除关键词过滤，逗号分隔。")
    parser.add_argument("--max-items", type=int, default=0, help="调试用，只导出前 N 个；0 表示不限制。")
    args = parser.parse_args()

    cookie = args.cookie.strip()
    if args.cookie_file:
        cookie = Path(args.cookie_file).read_text(encoding="utf-8").strip()
    if not cookie:
        raise SystemExit("请通过 --cookie 或 --cookie-file 提供 cookies。")

    include_keywords = split_keywords(args.include_keywords)
    exclude_keywords = split_keywords(args.exclude_keywords)

    out_dir = Path(args.out).resolve() if args.out.strip() else build_default_output_dir(
        personal_url=args.personal_url.strip(),
        cookie=cookie,
        include_keywords=include_keywords,
        exclude_keywords=exclude_keywords,
    )
    print(f"输出目录: {out_dir}")

    export_from_online(
        personal_url=args.personal_url.strip(),
        output_dir=out_dir,
        cookie=cookie,
        max_items=args.max_items,
        include_keywords=include_keywords,
        exclude_keywords=exclude_keywords,
    )


if __name__ == "__main__":
    main()
