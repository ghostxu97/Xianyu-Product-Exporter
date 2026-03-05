# Xianyu Product Exporter

本项目是一个「本地 WebUI + 在线抓取」的闲鱼商品导出工具。

支持能力：
- 按 `personal-url + cookies` 在线导出
- 商品介绍、现价、原价、多图（统一 JPG）落地到本地
- 关键词包含/排除过滤
- 可选是否导出已下架商品
- 导出结果标注商品状态（上架/下架）

## 界面截图
桌面端：

![WebUI Desktop](docs/screenshots/webui-desktop.png)

## 项目结构
- `webui_server.py`：Flask Web 服务
- `webui/index.html`：本地交互界面
- `export_goofish_products.py`：核心导出脚本
- `start_webui.sh`：一键启动 WebUI
- `SOP.md`：操作流程文档

## 快速开始
1. 安装依赖
```bash
python3 -m pip install flask requests beautifulsoup4 pillow
```

2. 启动 WebUI
```bash
./start_webui.sh
```

3. 打开页面
```text
http://127.0.0.1:8765
```

## WebUI 参数说明
- `个人主页 URL`：必填
- `Cookies`：必填
- `导出目录`：可空，空时自动生成目录名
- `包含关键词`：可选，逗号分隔
- `排除关键词`：可选，逗号分隔
- `导出已下架商品`：勾选=导出在售+已售出，不勾选=仅在售
- `最大导出数`：`0` 表示不限制

## 状态判定逻辑（关键）
状态判定与网页“筛选在售/已售出”一致：
- 先从 `mtop.idle.web.xyh.item.list` 的 `itemGroupList` 获取分组
- 按 `在售` 分组拉取并标记 `上架`
- 按 `已售出` 分组拉取并标记 `下架`

这比仅依赖详情字段更稳定。

## 导出结果
目录结构示例：

```text
导出目录/
  _source/personal.html
  0001-商品标题/
    product.json
    product.txt
    image_01.jpg
    image_02.jpg
```

`product.json` 主要字段：
- `item_id`
- `title`
- `description`
- `current_price`
- `original_price`
- `listing_status`（上架/下架）
- `listing_status_key`（状态来源字段）
- `listing_status_raw`（状态原始值）
- `item_url`
- `images_source`
- `images_local`

## CLI 用法（可选）
```bash
python3 export_goofish_products.py \
  --personal-url 'https://www.goofish.com/personal?userId=xxxx' \
  --cookie-file ./goofish_cookie.txt \
  --out ./products_export \
  --include-keywords 'toi,图益' \
  --exclude-keywords '配件' \
  --include-offline-items true \
  --max-items 0
```

## 安全建议
- 不要把 `cookies` 提交到仓库
- 导出结束后及时清理本地 cookie 文件
