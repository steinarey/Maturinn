// Read view: servings scaler, tap to check off ingredients and steps, keep screen awake.
(() => {
  const article = document.querySelector('.read');
  if (!article) return;
  const locale = article.dataset.lang === 'is' ? 'is-IS' : 'en-GB';
  const fmt = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 });

  const servings = document.getElementById('servings');
  if (servings) {
    const base = Number(servings.dataset.base);
    const qtys = [...document.querySelectorAll('[data-qty]')].map(el => ({
      el, value: Number(el.dataset.qty), unit: el.dataset.unit || '',
    }));
    servings.addEventListener('input', () => {
      const n = Number(servings.value);
      if (!(n > 0)) return;
      for (const q of qtys) q.el.textContent = `${fmt.format(q.value * n / base)} ${q.unit}`.trim();
    });
  }

  for (const li of document.querySelectorAll('.ingredients li.ing')) {
    li.addEventListener('click', () => li.classList.toggle('checked'));
  }
  for (const li of document.querySelectorAll('.steps > li')) {
    li.addEventListener('click', e => { if (!e.target.closest('a')) li.classList.toggle('done'); });
  }

  const wake = document.getElementById('wake');
  if (wake && 'wakeLock' in navigator) {
    wake.hidden = false;
    let lock = null;
    wake.addEventListener('click', async () => {
      if (lock) { await lock.release(); lock = null; wake.setAttribute('aria-pressed', 'false'); return; }
      try {
        lock = await navigator.wakeLock.request('screen');
        wake.setAttribute('aria-pressed', 'true');
        lock.addEventListener('release', () => { lock = null; wake.setAttribute('aria-pressed', 'false'); });
      } catch (_) { /* not allowed (e.g. battery saver) */ }
    });
  }
})();
