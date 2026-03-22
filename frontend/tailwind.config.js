/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: "#0f172a",
        card: "#1e293b",
        border: "#334155",
        accent: "#3b82f6",
        "accent-hover": "#2563eb",
        success: "#22c55e",
        danger: "#ef4444",
        warning: "#f59e0b",
        muted: "#64748b",
      },
    },
  },
  plugins: [],
};
