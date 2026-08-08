import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: ["selector", '[data-theme="dark"]'],
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "rgb(var(--background-rgb) / <alpha-value>)",
        surface: "rgb(var(--surface-rgb) / <alpha-value>)",
        card: "rgb(var(--card-rgb) / <alpha-value>)",
        subtle: "rgb(var(--subtle-rgb) / <alpha-value>)",
        foreground: "rgb(var(--foreground-rgb) / <alpha-value>)",
        "secondary-foreground": "rgb(var(--secondary-foreground-rgb) / <alpha-value>)",
        ink: "rgb(var(--foreground-rgb) / <alpha-value>)",
        muted: "rgb(var(--muted-rgb) / <alpha-value>)",
        border: "rgb(var(--border-rgb) / <alpha-value>)",
        control: "rgb(var(--control-border-rgb) / <alpha-value>)",
        primary: {
          DEFAULT: "rgb(var(--primary-rgb) / <alpha-value>)",
          hover: "rgb(var(--primary-hover-rgb) / <alpha-value>)",
          soft: "rgb(var(--primary-soft-rgb) / <alpha-value>)",
          foreground: "rgb(var(--primary-foreground-rgb) / <alpha-value>)",
          text: "rgb(var(--primary-text-rgb) / <alpha-value>)",
        },
        gold: {
          DEFAULT: "rgb(var(--primary-rgb) / <alpha-value>)",
          hover: "rgb(var(--primary-hover-rgb) / <alpha-value>)",
          soft: "rgb(var(--primary-soft-rgb) / <alpha-value>)",
          foreground: "rgb(var(--primary-foreground-rgb) / <alpha-value>)",
          text: "rgb(var(--primary-text-rgb) / <alpha-value>)",
        },
        emerald: {
          DEFAULT: "rgb(var(--emerald-rgb) / <alpha-value>)",
          dark: "rgb(var(--emerald-dark-rgb) / <alpha-value>)",
          pale: "rgb(var(--emerald-pale-rgb) / <alpha-value>)",
        },
        amber: {
          DEFAULT: "rgb(var(--amber-rgb) / <alpha-value>)",
          pale: "rgb(var(--amber-pale-rgb) / <alpha-value>)",
        },
        danger: {
          DEFAULT: "rgb(var(--danger-rgb) / <alpha-value>)",
          pale: "rgb(var(--danger-pale-rgb) / <alpha-value>)",
        },
        "document-paper": "rgb(var(--document-paper-rgb) / <alpha-value>)",
        "document-ink": "rgb(var(--document-ink-rgb) / <alpha-value>)",
        slate: {
          50: "rgb(var(--slate-50-rgb) / <alpha-value>)",
          100: "rgb(var(--slate-100-rgb) / <alpha-value>)",
          200: "rgb(var(--slate-200-rgb) / <alpha-value>)",
          300: "rgb(var(--slate-300-rgb) / <alpha-value>)",
          400: "rgb(var(--slate-400-rgb) / <alpha-value>)",
          500: "rgb(var(--slate-500-rgb) / <alpha-value>)",
          600: "rgb(var(--slate-600-rgb) / <alpha-value>)",
          700: "rgb(var(--slate-700-rgb) / <alpha-value>)",
          800: "rgb(var(--slate-800-rgb) / <alpha-value>)",
          900: "rgb(var(--slate-900-rgb) / <alpha-value>)",
        },
      },
      fontFamily: {
        arabic: ["Noto Sans Arabic", "Tahoma", "Arial", "sans-serif"],
        latin: ["Inter", "Segoe UI", "Arial", "sans-serif"],
      },
      boxShadow: {
        subtle: "0 18px 48px rgb(var(--shadow-rgb) / 0.18)",
        panel: "0 24px 70px rgb(var(--shadow-rgb) / 0.2)",
      },
      screens: {
        shell: "900px",
      },
    },
  },
  plugins: [],
};

export default config;
