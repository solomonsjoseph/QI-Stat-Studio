/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        canvas: '#F7F7F5',
        surface: '#FFFFFF',
        line: '#E8E7E3',
        ink: { DEFAULT: '#22252A', soft: '#5B6167', faint: '#878D94' },
        brand: { DEFAULT: '#2A527A', deep: '#1F3F5F', tint: '#EEF4FA', ring: '#BBD3EA' },
        ok: { bg: '#EDF3EC', ink: '#33633B' },
        warn: { bg: '#FBF3DB', ink: '#8A5A00' },
        error: { bg: '#FDECEC', ink: '#9F2D2D' },
      },
      fontFamily: {
        sans: ['system-ui', '-apple-system', 'Segoe UI', 'Helvetica Neue', 'Arial', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
