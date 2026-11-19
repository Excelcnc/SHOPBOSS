// Shows a drawing page or a quote preview over the app (the demo can't open new windows).
export function showViewer(f: { kind: "image" | "html"; content: string; title: string }) {
  document.getElementById("demo-viewer")?.remove();
  const wrap = document.createElement("div");
  wrap.id = "demo-viewer";
  wrap.setAttribute("role", "dialog");
  wrap.setAttribute("aria-label", f.title);
  wrap.className = "fixed inset-0 z-[60] flex items-center justify-center bg-navy-900/60 p-3 sm:p-6";
  const box = document.createElement("div");
  box.className = "flex max-h-full w-full max-w-4xl flex-col overflow-hidden rounded-lg bg-white shadow-xl";
  const head = document.createElement("div");
  head.className = "flex items-center gap-3 border-b border-steel-200 px-4 py-2";
  const h = document.createElement("div");
  h.className = "min-w-0 flex-1 truncate text-sm font-semibold";
  h.textContent = f.title;
  const close = document.createElement("button");
  close.className = "btn btn-sm";
  close.textContent = "Close";
  head.append(h, close);
  const body = document.createElement("div");
  body.className = "overflow-auto p-4";
  if (f.kind === "image") {
    const img = document.createElement("img");
    img.src = f.content; img.alt = f.title; img.className = "mx-auto max-w-full border border-steel-200";
    body.append(img);
  } else {
    body.innerHTML = f.content;  // built from escaped values in demo/api.ts
    body.classList.add("demo-quote");
  }
  box.append(head, body);
  wrap.append(box);
  const done = () => { wrap.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e: KeyboardEvent) => e.key === "Escape" && done();
  close.onclick = done;
  wrap.onclick = (e) => e.target === wrap && done();
  document.addEventListener("keydown", onKey);
  document.body.append(wrap);
  close.focus();
}
