// 结构自检：标签配平 + 幻灯片清单 + 关键元素检查
import fs from 'node:fs';

const file = process.argv[2];
const html = fs.readFileSync(file, 'utf8');

// 去掉 script / style 内容，避免误判
const stripped = html
  .replace(/<script[\s\S]*?<\/script>/gi, '<script></script>')
  .replace(/<style[\s\S]*?<\/style>/gi, '<style></style>')
  .replace(/<!--[\s\S]*?-->/g, '');

const VOID = new Set(['area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr']);
const stack = [];
const errors = [];
const tagRe = /<\/?([a-zA-Z][a-zA-Z0-9-]*)((?:"[^"]*"|'[^']*'|[^>"'])*)>/g;
let m;
while ((m = tagRe.exec(stripped)) !== null) {
  const raw = m[0], name = m[1].toLowerCase();
  const isClose = raw.startsWith('</');
  const selfClose = /\/>$/.test(raw) || VOID.has(name);
  if (name === 'br') continue;
  if (isClose) {
    if (!stack.length) { errors.push(`多余的结束标签 </${name}>`); continue; }
    const top = stack[stack.length - 1];
    if (top.name === name) stack.pop();
    else {
      const idx = stack.map(s => s.name).lastIndexOf(name);
      if (idx === -1) errors.push(`无法匹配的结束标签 </${name}>（当前栈顶 <${top.name}>）`);
      else { errors.push(`标签交叉嵌套：</${name}> 关闭时栈顶为 <${top.name}>`); stack.length = idx; }
    }
  } else if (!selfClose) {
    stack.push({ name });
  }
}
if (stack.length) errors.push('未闭合标签：' + stack.map(s => '<' + s.name + '>').join(', '));

const slides = [...html.matchAll(/<section class="slide([^"]*)"([^>]*)>/g)];
const titles = slides.map(s => (s[2].match(/data-title="([^"]*)"/) || [, '(无标题)'])[1]);
const secs = slides.map(s => (s[2].match(/data-sec="([^"]*)"/) || [, '(无)'])[1]);
const notes = (html.match(/class="note"/g) || []).length;

console.log('文件：', file);
console.log('大小：', (fs.statSync(file).size / 1024).toFixed(1), 'KB');
console.log('幻灯片数：', slides.length);
console.log('讲稿块数：', notes);
console.log('标签配平：', errors.length ? '❌\n  - ' + errors.join('\n  - ') : '✅ 全部配平');
console.log('\n页序：');
slides.forEach((s, i) => console.log(`  ${String(i + 1).padStart(2, '0')}  [${secs[i]}]  ${titles[i]}`));

const checks = [
  ['外部 http(s) 资源', /(src|href)\s*=\s*["']https?:\/\//i],
  ['遗留 </view> 误写', /<\/view>/i],
  ['未替换占位符', /\{\{[^}]*\}\}|TODO|FIXME/],
];
console.log('\n其他检查：');
for (const [label, re] of checks) {
  const hit = re.test(html);
  console.log(`  ${hit ? '❌ 命中' : '✅ 通过'}  ${label}`);
}
