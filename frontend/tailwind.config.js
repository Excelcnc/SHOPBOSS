/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "Segoe UI", "system-ui", "sans-serif"], mono: ["IBM Plex Mono", "ui-monospace", "Menlo", "monospace"] },
      colors: {
        navy: { 50: "#eef3fa", 100: "#d9e4f3", 600: "#1d4f91", 700: "#173f75", 800: "#14325c", 900: "#0e2442" },
        steel: { 50: "#f6f7f9", 100: "#eceef2", 200: "#dde1e7", 300: "#c3c9d3", 400: "#9aa3b1", 500: "#6f7a8a", 600: "#556070", 700: "#434c59", 800: "#2d343d", 900: "#1b2027" },
      },
    },
  },
  plugins: [],
};
