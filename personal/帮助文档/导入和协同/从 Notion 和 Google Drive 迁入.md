# 从 Notion / Google Drive 迁过来


## 从 Notion 迁

### 方式一：导出单个页面

适合只迁移部分内容。

1. 打开要导出的 Notion 页面
2. 点击右上角 **···** 菜单 → 「Export」
3. 弹窗中格式选 **Markdown & CSV**（AI 读 Markdown 效率最高，不要选 HTML）
4. 如需包含子页面，打开「Include subpages」
5. 点击 Export，下载 zip 文件

> Database 会导出为 CSV 文件；Callout 块会以 HTML 格式保留（Markdown 无等价格式）。

### 方式二：导出整个 Workspace

适合整体迁移，一次把所有内容打包。

**权限要求**：需要是 Workspace **Owner**（所有者）才能执行整体导出。

1. 打开 Notion，进入「Settings」→「General」
2. 找到「Export all workspace content」，点击导出
3. Notion 会发一封邮件给你，里面有下载链接（链接 7 天内有效）

> 导出处理最长需要 30 小时，取决于 workspace 体量。

***

## 从 Google Drive 迁

### 方式一：选中文件下载

适合只迁移部分内容。所有文件类型均支持。

1. 单击选中文件；按住 `Ctrl`（Mac 为 `⌘`）可多选，也可框选一批
2. 右键 → 「Download」，打包下载

> Google Docs / Sheets / Slides 会自动转换格式下载（Docs → `.docx`，Sheets → `.xlsx`，Slides → `.pptx`）。

### 方式二：导出整个 Google Drive

适合整体迁移，通过 Google Takeout 打包下载。

1. 前往 [takeout.google.com](https://takeout.google.com)
2. 取消全选，只勾选「Drive」
3. 选择导出格式和频率，点击「Create export」
4. Google 会发邮件通知你下载链接（视数据量，处理时间从几分钟到数小时不等）

***

## 导入 Moxt

有两个入口，选其一：

* **方式 A**：点击左侧边栏 Team Space 或 Personal Space 旁的 **+**

* **方式 B**：点击任意文件夹旁的 **···** 菜单

进入后选择「导入」，弹窗打开后将导出的文件拖拽上传即可。

***

## 常见问题

**Notion Database 的视图（看板、日历）会保留吗？**

不会。Database 导出为 CSV，数据和字段都在，但视图样式不保留。迁入 Moxt 后可以让 momo 重新生成 HTML 可视化。

**导入之后 AI 就能读这些内容了吗？**

是的。导入完成后 momo 就能访问这些文档。你可以问它：「我们之前有一篇关于 \[某个主题] 的文档，你能找到并总结一下吗？」
