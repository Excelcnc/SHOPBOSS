// "1" in the demo build (npm run build:demo): sample data and the cost engine run in the browser.
interface ImportMetaEnv { readonly VITE_DEMO?: string }
interface ImportMeta { readonly env: ImportMetaEnv }
declare module "*?url" { const url: string; export default url; }
