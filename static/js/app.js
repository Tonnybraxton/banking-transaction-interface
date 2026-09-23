document.querySelectorAll('[data-submit-guard]').forEach(form => {
  form.addEventListener('submit', () => {
    const button = form.querySelector('button[type="submit"], button:not([type])');
    if (button) { button.disabled = true; button.textContent = 'Processing…'; }
  });
});
window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
