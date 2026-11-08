// Write view: drag to reorder, remove rows/photos, pick ingredient suggestions.
(() => {
  const initSortable = root => {
    if (!window.Sortable) return;
    for (const list of root.querySelectorAll('.sortable')) {
      if (list.dataset.sortable) continue;
      list.dataset.sortable = '1';
      Sortable.create(list, { handle: '.handle', animation: 150 });
    }
  };
  window.addEventListener('load', () => initSortable(document));

  document.addEventListener('click', e => {
    const remove = e.target.closest('.remove');
    if (remove) { remove.closest('.row').remove(); return; }
    const removePhoto = e.target.closest('.remove-photo');
    if (removePhoto) { removePhoto.closest('.ph').remove(); return; }
    const use = e.target.closest('.use-suggestion');
    if (use) {
      const input = use.closest('.name').querySelector('input');
      input.value = use.dataset.name;
      input.dispatchEvent(new Event('change', { bubbles: true }));
      return;
    }
    const confirmBtn = e.target.closest('[data-confirm]');
    if (confirmBtn && !confirmBtn.dataset.armed) {
      // Two-step confirm: first click arms, second click submits.
      e.preventDefault();
      confirmBtn.dataset.armed = '1';
      confirmBtn.textContent = confirmBtn.dataset.confirm;
    }
  });

  // New rows: focus the first text field.
  document.body.addEventListener('htmx:afterSwap', e => {
    const list = e.detail.target;
    if (list.classList && list.classList.contains('rows')) {
      const last = list.lastElementChild;
      const field = last && last.querySelector('input[type=text], textarea');
      if (field) field.focus();
    }
  });
  // Clear the file input after an upload so the same file can be picked again.
  document.body.addEventListener('htmx:afterRequest', e => {
    if (e.target.type === 'file') e.target.value = '';
  });
})();
