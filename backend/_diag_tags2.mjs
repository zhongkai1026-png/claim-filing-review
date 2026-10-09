import fs from "node:fs";
const appJs = fs.readFileSync("D:\\Deepseek\\培训-债权申报与审查\\backend\\static\\js\\app.js", "utf8");
for (const name of ["ledgerTabsHtml", "acceptDateWarningHtml", "ledgerActionAreaHtml"]) {
  const i = appJs.indexOf(`function ${name}(`);
  const seg = appJs.slice(i, i + 4000);
  const body = seg.slice(0, seg.indexOf("\n}\n") + 2);
  const open = (body.match(/<div/g) || []).length, close = (body.match(/<\/div>/g) || []).length;
  console.log(`  ${name}: <div> ${open} / </div> ${close} ${open === close ? "✅" : "❌"}`);
}
