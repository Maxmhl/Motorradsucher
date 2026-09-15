/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: { 900: '#0b0f17', 800: '#121826', 700: '#1c2436', 600: '#2a3348' },
      },
    },
  },
  plugins: [],
}
