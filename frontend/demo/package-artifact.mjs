// After `vite build --mode demo`: writes dist-demo/page.html (the Artifact page body, without
// <html>/<head>/<body>, which the Artifact host adds) and copies the recorded sample data next to it.
import fs from "fs";
import { transformSync } from "esbuild";
const dist = new URL("../dist-demo/", import.meta.url);
const html = fs.readFileSync(new URL("index.html", dist), "utf8");
const js = html.match(/<script type="module"[^>]*src="([^"]+)"/)[1];
const css = html.match(/<link rel="stylesheet"[^>]*href="(\.\/assets\/[^"]+\.css)"/)[1];
const page = `<title>CNC Quote Demo</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap">
<link rel="stylesheet" href="${css.replace(/^\.\//, "")}">
<style>
  /* One deliberate light look, the same as the installed app. */
  :root { color-scheme: light; }
  html, body { height: 100%; }
  body { background: #f6f7f9; color: #1b2027; font-family: Inter, "Segoe UI", system-ui, sans-serif; -webkit-font-smoothing: antialiased; }
  #boot { display: grid; place-items: center; height: 100%; color: #556070; font-size: 14px; }
</style>
<div id="root"><div id="boot">Loading CNC Quote…</div></div>
<script type="module" src="${js.replace(/^\.\//, "")}"></script>
`;
fs.writeFileSync(new URL("page.html", dist), page);
fs.copyFileSync(new URL("./demo-data.json", import.meta.url), new URL("demo-data.json", dist));
// The publish service refuses raw control characters (some libraries embed them in strings):
// write them as \\xNN escapes inside the strings that hold them (identical behaviour).
for (const f of fs.readdirSync(new URL("assets/", dist))) {
  if (!/\.m?js$/.test(f)) continue;
  const u = new URL("assets/" + f, dist);
  const src = fs.readFileSync(u, "utf8");
  if (!/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(src)) continue;
  // Every such character in these libraries sits inside a string literal, where "\xNN" is the same value.
  // (\v and \f could also be whitespace outside strings, so stop if they ever appear.)
  if (/[\x0b\x0c]/.test(src)) throw new Error(`${f}: vertical tab / form feed found; escape it by hand`);
  const out = src.replace(/[\x00-\x08\x0e-\x1f]/g, (c) => "\\x" + c.charCodeAt(0).toString(16).padStart(2, "0"));
  transformSync(out, { format: "esm", loader: "js" });  // throws if the result is no longer valid JavaScript
  fs.writeFileSync(u, out);
  console.log("escaped control characters in", f);
}
const files = fs.readdirSync(new URL("assets/", dist)).map((f) => "assets/" + f);
fs.writeFileSync(new URL("files.json", dist), JSON.stringify(files, null, 1));
console.log("page.html +", files.length, "asset files + demo-data.json");
