import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        ink: "#102a43",
        muted: "#62758a",
        border: "#d9e2ec",
        emerald: {
          DEFAULT: "#07845c",
          dark: "#056a4a",
          pale: "#e8f5f0",
        },
        amber: {
          DEFAULT: "#f59e0b",
          pale: "#fff7e6",
        },
        danger: {
          DEFAULT: "#dc2626",
          pale: "#fef2f2",
        },
      },
      fontFamily: {
        arabic: ["Noto Sans Arabic", "Tahoma", "Arial", "sans-serif"],
        latin: ["Inter", "Segoe UI", "Arial", "sans-serif"],
      },
      boxShadow: {
        subtle: "0 8px 26px rgba(16, 42, 67, 0.07)",
      },
    },
  },
  plugins: [],
};

export default config;
