/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        bg: 'var(--bg)',
        bg2: 'var(--bg2)',
        bg3: 'var(--bg3)',
        sb: 'var(--sb)',
        fg: 'var(--fg)',
        fg2: 'var(--fg2)',
        fg3: 'var(--fg3)',
        fg4: 'var(--fg4)',
        bdr: 'var(--bdr)',
        bdr2: 'var(--bdr2)',
        ac: 'var(--ac)',
        'ac-h': 'var(--ac-h)',
        'ac-bg': 'var(--ac-bg)',
        'ac-fg': 'var(--ac-fg)',
        card: 'var(--card)',
        code: 'var(--code)',
        'code-b': 'var(--code-b)',
        ok: 'var(--ok)',
        warn: 'var(--warn)',
        err: 'var(--err)',
      },
      fontFamily: {
        sans: ['Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'Menlo', 'monospace'],
      },
      maxWidth: { msg: '760px' },
      borderRadius: { r: '10px', rs: '8px', rx: '6px' },
      transitionTimingFunction: { e: 'cubic-bezier(.4,0,.2,1)', es: 'cubic-bezier(.34,1.56,.64,1)' },
    },
  },
  plugins: [],
}
