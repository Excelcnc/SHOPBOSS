// Compares the browser engine (src/demo/engine.ts) with Python results: node demo/check-engine.mjs py_results.json
import { buildSync } from "esbuild";
import fs from "fs";
const outFile = new URL("./.engine.mjs", import.meta.url).pathname;
buildSync({ entryPoints: [new URL("../src/demo/engine.ts", import.meta.url).pathname], outfile: outFile, format: "esm", bundle: true, platform: "node" });
const { estimate } = await import(outFile);
const d = JSON.parse(fs.readFileSync(new URL("./demo-data.json", import.meta.url)));
const py = JSON.parse(fs.readFileSync(process.argv[2]));
let bad = 0, n = 0;
const close = (a, b) => (typeof a === "number" && typeof b === "number") ? Math.abs(a - b) <= 1e-6 * Math.max(1, Math.abs(b)) : JSON.stringify(a) === JSON.stringify(b);
for (const [k, want] of Object.entries(py.out)) {
  const [vid, i, qs] = k.split(":");
  const inp = d.engine_inputs[vid];
  const x = qs === "None" ? inp : { ...inp, quantities: JSON.parse(qs) };
  const got = estimate(x, py.scen[+i]);
  n++;
  const diffs = [];
  want.breaks.forEach((b, j) => { for (const f of Object.keys(b)) if (!close(got.breaks[j]?.[f], b[f])) diffs.push(`break ${b.qty}.${f}: js ${got.breaks[j]?.[f]} py ${b[f]}`); });
  want.lines.forEach((l, j) => { const gl = got.lines[j]; if (!gl || gl.key !== l.key || !close(gl.value, l.value) || !close(gl.computed, l.computed) || gl.note !== l.note) diffs.push(`line ${l.key}: js ${JSON.stringify(gl && [gl.computed, gl.value, gl.note])} py ${JSON.stringify([l.computed, l.value, l.note])}`); });
  for (const f of ["adjustments", "warnings"]) if (JSON.stringify(got[f]) !== JSON.stringify(want[f])) diffs.push(f);
  if (JSON.stringify(got.complexity.drivers) !== JSON.stringify(want.complexity.drivers)) diffs.push("drivers " + JSON.stringify(got.complexity.drivers) + " vs " + JSON.stringify(want.complexity.drivers));
  if (got.machine.why !== want.machine.why) diffs.push("machine.why");
  if (diffs.length) { bad++; console.log(k, diffs.slice(0, 4)); }
}
fs.unlinkSync(outFile);
console.log(`${n - bad}/${n} cases identical`);
process.exit(bad ? 1 : 0);
