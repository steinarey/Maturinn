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

  // Enter in a text field shouldn't save the recipe; only the save button does. Block just the
  // submit that Enter triggers (same task as the keypress), so Enter still picks a suggestion.
  let enterPressed = false;
  document.addEventListener('keydown', e => {
    if (e.key === 'Enter' && e.target.matches('#recipe-form input')) {
      enterPressed = true;
      setTimeout(() => { enterPressed = false; }, 0);
    }
  });
  document.addEventListener('submit', e => {
    if (e.target.id === 'recipe-form' && enterPressed) e.preventDefault();
  });

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

  // "Link a recipe" picker: inserts [title](recipe:ID) at the cursor of the field it was opened from.
  // With text selected, the selection becomes the link label.
  const picker = document.getElementById('link-picker');
  let linkTarget = null;
  let lastFocused = null;  // where the cursor was before clicking the link button
  document.addEventListener('focusin', e => { if (e.target.matches('textarea')) lastFocused = e.target; });
  document.addEventListener('click', e => {
    const open = e.target.closest('[data-picker]');
    if (open && picker) {
      linkTarget = open.closest('.row, .field').querySelector('textarea');
      picker.showModal();
      const q = picker.querySelector('input[type=search]');
      q.value = '';
      q.focus();
      htmx.trigger(q, 'input');
      return;
    }
    const pick = e.target.closest('.pick');
    if (pick && linkTarget) {
      const { value } = linkTarget;
      // Cursor position if the user was typing in this field; otherwise append.
      let [a, b] = lastFocused === linkTarget
        ? [linkTarget.selectionStart, linkTarget.selectionEnd] : [value.length, value.length];
      let link = pick.dataset.link;
      if (a === value.length && value && !/\s$/.test(value)) link = ' ' + link;
      if (b > a) link = link.replace(/^\[[^\]]*\]/, `[${value.slice(a, b).replace(/[\[\]\n]/g, '')}]`);
      linkTarget.value = value.slice(0, a) + link + value.slice(b);
      picker.close();
      linkTarget.focus();
      linkTarget.setSelectionRange(a + link.length, a + link.length);
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
