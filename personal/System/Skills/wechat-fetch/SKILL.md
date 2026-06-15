***

name: wechat-fetch
description: "抓取微信公众号文章纯文字正文，保存为 Markdown 文件。只还原段落、加粗、标题、引用等文字格式，跳过图片、音频、视频"
allowed-tools:

* Bash

* Read

* Write

* Edit

* Glob

***

# 微信公众号文章纯文本抓取 Skill

将微信公众号文章链接抓取为纯文字正文，保存为 Markdown 文件。**不下载图片，不处理音视频**，只还原文字内容和格式。

## 使用方式

用户提供微信文章链接和目标路径，如：

```
https://mp.weixin.qq.com/s/xxxxxx  →  team/xxx/文章名.md
```

参数：`$ARGUMENTS` — 文章 URL（必填）+ 输出文件路径（可选，默认 `/tmp/wechat_article.md`）

***

## 核心原则：只还原文字

只抓取纯文字内容和格式（段落、加粗、标题、引用），不下载图片，不处理音视频，截断文末无关内容。

***

## 完整流程

### Step 1：抓取页面 HTML

```python
import requests, re

url = "https://mp.weixin.qq.com/s/xxxxxx"
headers = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "Accept-Language": "zh-CN,zh;q=0.9",
}
resp = requests.get(url, headers=headers, timeout=30)
resp.encoding = "utf-8"
html = resp.text
```

**踩坑**：必须用移动端 UA，PC 端有时要求 JS 执行。

### Step 2：定位正文区域

```python
match = re.search(r'id="js_content"[^>]*>(.*)', html, re.DOTALL)
content_html = match.group(1)[:200000]
```

### Step 3：提取元信息

```python
# 标题
title_match = re.search(r'<h1[^>]*class="[^"]*rich_media_title[^"]*"[^>]*>\s*(.*?)\s*</h1>', html, re.DOTALL)
title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip() if title_match else "未知标题"

# 发布时间
date_match = re.search(r'id="publish_time"[^>]*>(.*?)</em>', html, re.DOTALL)
pub_date = date_match.group(1).strip() if date_match else "未获取"

# 公众号名称
account_match = re.search(r'id="js_name"[^>]*>(.*?)</a>', html, re.DOTALL)
if account_match:
    account = re.sub(r'<[^>]+>', '', account_match.group(1)).strip().split('\n')[0].strip()
else:
    account = "未知公众号"
```

**踩坑**：`js_name` 后面有大量嵌套空白，必须 `.split('\n')[0].strip()` 只取第一行。

### Step 4：去除图片和媒体标签

在转换格式前，直接将图片、视频、音频标签从 HTML 中抹掉，不做任何替换：

```python
# 去掉所有 img 标签（含微信 data-src 图片）
content_html = re.sub(r'<img[^>]*/?\s*>', '', content_html)

# 去掉视频嵌入组件
content_html = re.sub(r'<qqvideo[^>]*/?\s*>', '', content_html)
content_html = re.sub(r'<mp-video[^>]*>.*?</mp-video>', '', content_html, flags=re.DOTALL)
content_html = re.sub(r'<video[^>]*>.*?</video>', '', content_html, flags=re.DOTALL)

# 去掉音频嵌入
content_html = re.sub(r'<audio[^>]*>.*?</audio>', '', content_html, flags=re.DOTALL)
content_html = re.sub(r'<mpvoice[^>]*/?\s*>', '', content_html)
```

### Step 5：HTML → Markdown，保留文字格式

```python
# 加粗：font-weight: 600/bold/700
def bold_span(m):
    text = re.sub(r'<[^>]+>', '', m.group(0)).strip()
    return f'**{text}**' if text else ''

content_html = re.sub(
    r'<span[^>]*font-weight:\s*(?:600|bold|700)[^>]*>.*?</span>',
    bold_span, content_html, flags=re.DOTALL
)

# <strong> 和 <b>
content_html = re.sub(
    r'<strong[^>]*>(.*?)</strong>',
    lambda m: f'**{re.sub(r"<[^>]+>", "", m.group(1)).strip()}**' if re.sub(r'<[^>]+>', '', m.group(1)).strip() else '',
    content_html, flags=re.DOTALL
)
content_html = re.sub(
    r'<b[^>]*>(.*?)</b>',
    lambda m: f'**{re.sub(r"<[^>]+>", "", m.group(1)).strip()}**' if re.sub(r'<[^>]+>', '', m.group(1)).strip() else '',
    content_html, flags=re.DOTALL
)

# 斜体
content_html = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', content_html, flags=re.DOTALL)
content_html = re.sub(r'<i[^>]*>(.*?)</i>', r'*\1*', content_html, flags=re.DOTALL)

# 引用块
content_html = re.sub(
    r'<section[^>]*data-mpa-md-key="blockquote"[^>]*>(.*?)</section>\s*</section>',
    lambda m: '\n> ' + re.sub(r'<[^>]+>', '', m.group(1)).strip().replace('\n', '\n> ') + '\n',
    content_html, flags=re.DOTALL
)

# 大字号 → 标题层级
def fontsize_to_heading(m):
    size = int(m.group(1))
    text = re.sub(r'<[^>]+>', '', m.group(2)).strip()
    if not text: return ''
    if size >= 24: return f'\n\n## {text}\n\n'
    elif size >= 20: return f'\n\n### {text}\n\n'
    elif size >= 18: return f'\n\n#### {text}\n\n'
    return text

content_html = re.sub(
    r'<(?:span|p|section)[^>]*font-size:\s*(\d+)px[^>]*>(.*?)</(?:span|p|section)>',
    fontsize_to_heading, content_html, flags=re.DOTALL
)

# h1-h4 标签
for level in range(1, 5):
    content_html = re.sub(
        rf'<h{level}[^>]*>(.*?)</h{level}>',
        lambda m, l=level: f'\n\n{"#" * (l+1)} {re.sub(r"<[^>]+>", "", m.group(1)).strip()}\n\n',
        content_html, flags=re.DOTALL
    )

# data-mpa-md-key="heading"
content_html = re.sub(
    r'<section[^>]*data-mpa-md-key="heading"[^>]*>(.*?)</section>',
    lambda m: f'\n\n## {re.sub(r"<[^>]+>", "", m.group(1)).strip()}\n\n',
    content_html, flags=re.DOTALL
)

# 水平线
content_html = re.sub(r'<hr[^>]*/?\s*>', '\n\n---\n\n', content_html)

# 块级标签 → 换行
content_html = re.sub(r'</p>', '\n\n', content_html)
content_html = re.sub(r'<br\s*/?>', '\n', content_html)
content_html = re.sub(r'</section>', '\n', content_html)
content_html = re.sub(r'</div>', '\n', content_html)

# 去掉剩余 HTML 标签
text = re.sub(r'<[^>]+>', '', content_html)

# 解码 HTML 实体
for old, new in [('&nbsp;',' '), ('&lt;','<'), ('&gt;','>'), ('&amp;','&'),
                  ('&#8203;',''), ('&ldquo;','\u201c'), ('&rdquo;','\u201d'),
                  ('&lsquo;','\u2018'), ('&rsquo;','\u2019'), ('&mdash;','—'), ('&ndash;','–')]:
    text = text.replace(old, new)

# 清理空加粗
text = re.sub(r'\*\*\s*\*\*', '', text)
```

### Step 6：段落空行处理

```python
lines = text.split('\n')
lines = [line.strip() for line in lines]

# 截断 JS 代码
clean_lines = []
for line in lines:
    if re.match(r'^var \w+|^if \(|^document\.|^window\.|^function\s|^\(function|^try\s*\{', line):
        break
    clean_lines.append(line)

# 截断文末无关内容
final_lines = []
for line in clean_lines:
    if line in ['往期回顾', '往期精选', '推荐阅读', '相关推荐']:
        break
    final_lines.append(line)

# 去掉首尾空行
while final_lines and not final_lines[0]: final_lines.pop(0)
while final_lines and not final_lines[-1]: final_lines.pop()

# 确保每个有内容的行之间都有空行
result = []
for i, line in enumerate(final_lines):
    result.append(line)
    if (line.strip() and
        i + 1 < len(final_lines) and
        final_lines[i+1].strip() and
        not line.startswith('#') and
        not line.startswith('>') and
        not line.startswith('---')):
        result.append('')

full_text = '\n'.join(result)
full_text = re.sub(r'\n{3,}', '\n\n', full_text)
```

### Step 7：组装最终文档

```python
from datetime import date

output = f'# {title}\n\n> **来源**：公众号「{account}」· **原文链接**：[查看原文]({url})\n> **发布时间**：{pub_date} · **采集时间**：{date.today().isoformat()}\n\n---\n\n{full_text}\n'

with open(output_path, "w", encoding="utf-8") as f:
    f.write(output)
```

### Step 8：最终检查

1. **空行检查**：随机抽 3 段看是否有空行分隔
2. **加粗检查**：搜索 `**` 确认加粗存在
3. **末尾检查**：确认没有"往期回顾"等无关内容
4. **图片检查**：确认文中没有 `![` 或 `mmbiz.qpic.cn`（如有说明 Step 4 有遗漏）

***

## 访谈/对谈类文章的特殊处理

如果正文包含多个说话人（出现 `XXX：` 格式），额外处理：

```python
speakers = re.findall(r'^([^：:]{2,8})[：:]', full_text, re.MULTILINE)
for speaker in set(speakers):
    full_text = re.sub(
        rf'\n{re.escape(speaker)}[：:]',
        f'\n\n**{speaker}：** ',
        full_text
    )
```

***

## 踩坑记录

* **`js_name`** **内容污染**：`.split('\n')[0].strip()` 只取第一行

* **段落空行丢失**：HTML → 纯文本后段落会挤在一起，必须在输出前补空行

* **`font-weight: 600`**：微信常用 600 而非 bold/strong，三种都要检测

* **文末无关内容**：在"往期回顾"处截断

## 已知限制

1. 付费/登录墙：部分文章需要关注公众号才能阅读
2. 文章已删除：返回空正文
3. 公众号合集：新格式合集页 `js_content` 可能定位失败

## 处理多篇文章

用户提供多个链接时，逐一处理，每篇单独保存。文件名建议格式：`序号-文章标题.md`。
