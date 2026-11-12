import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";

const wheelsDir = path.join(process.cwd(), "wheels");
const outDir = path.join(process.cwd(), "pylib");
fs.mkdirSync(wheelsDir, { recursive: true });
fs.mkdirSync(outDir, { recursive: true });

async function fetchWheel(name, url) {
  const p = path.join(wheelsDir, name);
  if (fs.existsSync(p)) return p;
  const bin = Buffer.from(await (await fetch(url)).arrayBuffer());
  fs.writeFileSync(p, bin);
  console.log("downloaded", name, bin.length);
  return p;
}

await fetchWheel("pyinstaller-6.22.3-py3-none-win_amd64.whl",
  "https://pypi.tuna.tsinghua.edu.cn/packages/source/p/pyinstaller/pyinstaller-6.22.3-py3-none-win_amd64.whl");

function extractZip(file, dest) {
  const buf = fs.readFileSync(file);
  let eocd = -1;
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 70000); i--) {
    if (buf.readUInt32LE(i) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error("no eocd in " + file);
  const count = buf.readUInt16LE(eocd + 10);
  let off = buf.readUInt32LE(eocd + 16);
  let n = 0;
  for (let k = 0; k < count; k++) {
    if (buf.readUInt32LE(off) !== 0x02014b50) break;
    const method = buf.readUInt16LE(off + 10);
    const compSize = buf.readUInt32LE(off + 20);
    const nameLen = buf.readUInt16LE(off + 28);
    const extraLen = buf.readUInt16LE(off + 30);
    const commentLen = buf.readUInt16LE(off + 32);
    const localOff = buf.readUInt32LE(off + 42);
    const name = buf.toString("utf8", off + 46, off + 46 + nameLen);
    off += 46 + nameLen + extraLen + commentLen;
    if (name.endsWith("/")) continue;
    const lNameLen = buf.readUInt16LE(localOff + 26);
    const lExtraLen = buf.readUInt16LE(localOff + 28);
    const dataStart = localOff + 30 + lNameLen + lExtraLen;
    const raw = buf.subarray(dataStart, dataStart + compSize);
    let data;
    if (method === 0) data = raw;
    else if (method === 8) data = zlib.inflateRawSync(raw);
    else continue;
    const target = path.join(dest, name);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, data);
    n++;
  }
  return n;
}

for (const f of fs.readdirSync(wheelsDir).filter(f => f.endsWith(".whl"))) {
  try {
    const n = extractZip(path.join(wheelsDir, f), outDir);
    console.log("extracted", f, n, "files");
  } catch (e) {
    console.log("extract fail", f, e.message);
  }
}
