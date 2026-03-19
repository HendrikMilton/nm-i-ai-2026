/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/**/*.{js,ts,jsx,tsx}",
    "./src/index.html",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['Roboto Mono', 'monospace'],
      },
      colors: {
        background: 'rgb(var(--background) / <alpha-value>)',
        foreground: 'rgb(var(--foreground) / <alpha-value>)',
        surface: 'rgb(var(--surface) / <alpha-value>)',
        'surface-dim': 'rgb(var(--surface-dim) / <alpha-value>)',
        border: 'rgb(var(--border) / <alpha-value>)',
        primary: 'rgb(var(--primary) / <alpha-value>)',
        secondary: 'rgb(var(--secondary) / <alpha-value>)',
        muted: 'rgb(var(--muted) / <alpha-value>)',
        error: 'rgb(var(--error) / <alpha-value>)',
        success: 'rgb(var(--success) / <alpha-value>)',
        warning: 'rgb(var(--warning) / <alpha-value>)',
      },
      boxShadow: {
        'gcp': '0 1px 2px 0 rgba(60,64,67,0.3), 0 1px 3px 1px rgba(60,64,67,0.15)',
      },
    },
  },
  darkMode: 'class',
  plugins: [
    function({ addBase }) {
      addBase({
        ':root': {
          '--background': '248 249 250',
          '--foreground': '32 33 36',
          '--surface': '255 255 255',
          '--surface-dim': '241 243 244',
          '--border': '218 220 224',
          '--primary': '26 115 232',
          '--secondary': '117 117 117',
          '--muted': '158 158 158',
          '--error': '217 48 37',
          '--success': '24 128 56',
          '--warning': '249 171 0',
        },
        '.dark': {
          '--background': '32 33 36',
          '--foreground': '232 234 237',
          '--surface': '41 42 45',
          '--surface-dim': '53 54 58',
          '--border': '95 99 104',
          '--primary': '138 180 248',
          '--secondary': '154 160 166',
          '--muted': '154 160 166',
          '--error': '242 139 130',
          '--success': '129 201 149',
          '--warning': '253 214 99',
        },
      });
    },
  ],
};
