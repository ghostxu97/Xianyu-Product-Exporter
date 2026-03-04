# 闲鱼商品导出助手

本项目是一个「本地 Web 交互 + 闲鱼在线导出」工具：
- 在本地网页填写参数并点击导出
- 后端通过 `personal-url + cookies` 在线抓取商品
- 支持关键词包含/排除过滤
- 支持选择是否导出已下架商品
- 导出为一个商品一个文件夹（含介绍、价格、图片）

## 目录
- `webui_server.py`：Web 服务（Flask）
- `webui/index.html`：本地交互页面
- `export_goofish_products.py`：核心导出逻辑
- `start_webui.sh`：启动脚本

## 快速开始
1. 安装依赖
```bash
python3 -m pip install flask requests beautifulsoup4 pillow
```

2. 启动
```bash
./start_webui.sh
```

3. 打开页面
```text
http://127.0.0.1:8765
```

## 核心能力
- 通过接口获取个人主页商品列表与商品详情
- 预筛选阶段逐条输出：`x/N 命中/跳过：商品名`
- 导出阶段输出：`导出商品 a/b`
- 导出结果内标注商品状态：`上架 / 下架 / 未知`
- 支持默认导出目录自动命名：
  - `闲鱼昵称_userid_时间戳_inc-包含关键词_exc-排除关键词`

## 安全建议
- `cookies` 仅本地使用，不要提交到仓库
- 导出完成后及时删除本地 cookie 文件
