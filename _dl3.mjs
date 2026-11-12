import fs from "node:fs";
import path from "node:path";
const p = path.join(process.cwd(), "wheels", "pyinstaller-6.22.3-py3-none-win_amd64.whl");
fs.rmSync(p, { force: true });
const res = await fetch("https://pypi.org/pypi/pyinstaller/json");
console.log("json status", res.status);
const j = await res.json();
const urls = j.releases?.["6.22.3"] || j.urls || [];
const hit = urls.find(u => u.filename === "pyinstaller-6.22.3-py3-none-win_amd64.whl");
if (!hit) { console.log("no hit", urls.map(u => u.filename).slice(0, 5)); }
else {
  const bin = Buffer.from(await (await fetch(hit.url)).arrayBuffer());
  fs.writeFileSync(p, bin);
  console.log("ok", bin.length);
}
