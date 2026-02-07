/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // ADA Design System colors
        'background': '#0a0e1a',
        'surface': '#111827',
        'surface-elevated': '#1f2937',
        'primary': '#3b82f6',
        'secondary': '#8b5cf6',
        'accent': '#10b981',
        'warning': '#f59e0b',
        'danger': '#ef4444',
        // Legacy moltbot colors (preserved for compatibility)
        'moltbot': {
          'primary': '#6366f1',
          'secondary': '#8b5cf6',
          'dark': '#1e1e2e',
          'surface': '#282a36',
          'border': '#44475a',
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'sans-serif'],
      },
      backdropBlur: {
        'glass': '24px',
      },
    },
  },
  plugins: [],
}
