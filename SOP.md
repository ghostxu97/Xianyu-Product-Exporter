# SOP：闲鱼商品导出助手

## 1. 启动服务
```bash
cd /Users/xuguowei/Downloads/闲鱼/导出闲鱼商品详情webUi
./start_webui.sh
```

## 2. 页面操作
访问 `http://127.0.0.1:8765`，填写：
- 个人主页 URL（必须）
- Cookies（必须）
- 导出目录（可空，空时自动生成）
- 包含关键词（可选，逗号分隔）
- 排除关键词（可选，逗号分隔）
- 最大导出数（可选，`0` 为不限制）

## 3. 日志含义
- `x/N 命中：商品名`：预筛选命中
- `x/N 跳过：商品名`：预筛选被过滤掉
- `导出商品 a/b`：进入实际导出阶段

## 4. 输出结构
```text
导出目录/
  _source/personal.html
  0001-商品标题/
    product.json
    product.txt
    image_01.jpg
```

## 5. 常见问题
- `FAIL_BIZ_FORBIDDEN`：平台分页上限，脚本会自动停止翻页并继续导出已拿到的数据
- 昵称是 `unknown`：检查 cookie 是否过期；脚本会从多个字段兜底取昵称
- 页面提示旧文案：强刷浏览器缓存（`Cmd+Shift+R`）
