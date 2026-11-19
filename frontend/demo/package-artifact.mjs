// After `vite build --mode demo`: writes dist-demo/page.html (the Artifact page body, without
// <html>/<head>/<body>, which the Artifact host adds) and copies the recorded sample data next to it.
import fs from "fs";
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
const files = fs.readdirSync(new URL("assets/", dist)).map((f) => "assets/" + f);
fs.writeFileSync(new URL("files.json", dist), JSON.stringify(files, null, 1));
console.log("page.html +", files.length, "asset files + demo-data.json");
