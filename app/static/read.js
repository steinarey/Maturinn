// Read view: servings scaler, tap to check off ingredients and steps, keep screen awake.
(() => {
  const article = document.querySelector('.read');
  if (!article) return;
  // Servings and the cups -> dl/ml switch: the server picks units (3 tsk -> 1 msk), so ask it.
  const servings = document.getElementById('servings');
  const metric = document.getElementById('metric');
  let pending = null;
  const refresh = () => {
    const params = new URLSearchParams();
    if (servings && Number(servings.value) > 0) params.set('servings', servings.value);
    if (metric && metric.checked) params.set('metric', 'true');
    clearTimeout(pending);
    pending = setTimeout(async () => {
      const resp = await fetch(`${article.dataset.amounts}?${params}`);
      if (!resp.ok) return;
      const amounts = await resp.json();
      for (const el of document.querySelectorAll('[data-ri]')) {
        if (el.dataset.ri in amounts) el.textContent = amounts[el.dataset.ri];
      }
    }, 150);
  };
  if (servings) servings.addEventListener('input', refresh);
  if (metric) metric.addEventListener('change', refresh);
  // The browser may restore the inputs on back/reload while the text is the default.
  if ((metric && metric.checked) || (servings && servings.value !== servings.dataset.base)) refresh();

  for (const li of document.querySelectorAll('.ingredients li.ing')) {
    li.addEventListener('click', () => li.classList.toggle('checked'));
  }
  for (const li of document.querySelectorAll('.steps > li')) {
    li.addEventListener('click', e => { if (!e.target.closest('a')) li.classList.toggle('done'); });
  }

  // Shopping list dialog: the button loads its content with htmx; we only open/close it.
  const shop = document.getElementById('shop');
  const shopOpen = document.getElementById('shop-open');
  if (shop && shopOpen) {
    const loading = shop.querySelector('#shop-body').innerHTML;
    shopOpen.addEventListener('click', () => { shop.querySelector('#shop-body').innerHTML = loading; shop.showModal(); });
    shop.addEventListener('click', e => { if (e.target.closest('[data-close]') || e.target === shop) shop.close(); });
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
