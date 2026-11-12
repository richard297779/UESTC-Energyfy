import fs from "node:fs";
import path from "node:path";
const dir = path.join(process.cwd(), "wheels");
fs.mkdirSync(dir, { recursive: true });

async function grab(pkg, re) {
  const res = await fetch("https://pypi.tuna.tsinghua.edu.cn/simple/" + pkg + "/");
  const html = await res.text();
  let files = [...html.matchAll(/href="([^"#]+\.whl)/g)].map(m => m[1]).filter(u => re.test(decodeURIComponent(u.split("/").pop())));
  if (!files.length) { console.log("MISS", pkg); return; }
  files.sort();
  const pick = files[files.length - 1];
  const abs = pick.startsWith("http") ? pick : "https://pypi.tuna.tsinghua.edu.cn" + (pick.startsWith("/") ? pick : "/" + pick);
  const name = decodeURIComponent(abs.split("/").pop());
  const bin = Buffer.from(await (await fetch(abs)).arrayBuffer());
  fs.writeFileSync(path.join(dir, name), bin);
  console.log("OK", name, bin.length);
}
await grab("altgraph", /^altgraph-[\d.]+-py2\.py3-none-any\.whl$/);
await grab("pyinstaller", /^pyinstaller-[\d.]+-py3-none-win_amd64\.whl$/);
