(() => {
  const storageKey = 'junction.theme';
  const systemTheme = window.matchMedia('(prefers-color-scheme: dark)');
  let preference = null;
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved === 'dark' || saved === 'light') preference = saved;
  } catch { /* Theme switching also works when browser storage is unavailable. */ }

  function applyTheme(theme) {
    document.documentElement.dataset.theme = theme;
    const toggle = document.getElementById('theme-toggle');
    if (toggle) {
      toggle.setAttribute('aria-pressed', String(theme === 'dark'));
      toggle.title = theme === 'dark' ? 'Use light mode' : 'Use dark mode';
    }
  }

  applyTheme(preference || (systemTheme.matches ? 'dark' : 'light'));
  document.addEventListener('DOMContentLoaded', () => {
    applyTheme(document.documentElement.dataset.theme);
    document.getElementById('theme-toggle')?.addEventListener('click', () => {
      preference = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem(storageKey, preference); } catch { /* Optional persistence. */ }
      applyTheme(preference);
    });
  });
  systemTheme.addEventListener('change', event => {
    if (!preference) applyTheme(event.matches ? 'dark' : 'light');
  });
})();
