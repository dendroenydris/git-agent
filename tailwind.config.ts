import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./app/**/*.{js,ts,jsx,tsx,mdx}'],
  theme: {
    extend: {
      colors: {
        'mac-gray': '#f5f5f7',
        'mac-border': '#e5e5e5',
        'mac-hover': '#0071e3',
      },
      boxShadow: {
        'mac': '0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06)',
      },
    },
  },
  plugins: [],
}

export default config 