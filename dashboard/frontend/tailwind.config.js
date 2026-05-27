/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg:      '#0f1117',
        surface: '#161b27',
        border:  '#252d3d',
        muted:   '#4b5563',
        dim:     '#8892a4',
        primary: '#e2e8f0',
        green:   '#10b981',
        red:     '#f43f5e',
        amber:   '#f59e0b',
        blue:    '#3b82f6',
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
}
