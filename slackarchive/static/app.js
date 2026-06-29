// slack-archive: minimal client-side behaviour (no external libraries).

// 1) Inline thread expand/collapse on conversation pages.
document.addEventListener('click', async (e) => {
  const btn = e.target.closest('.thread-btn');
  if (!btn) return;
  const mount = btn.nextElementSibling;
  if (!mount || !mount.classList.contains('thread-mount')) return;

  // Toggle if already loaded.
  if (mount.dataset.loaded === '1') {
    mount.hidden = !mount.hidden;
    return;
  }
  const conv = btn.dataset.conv;
  const ts = btn.dataset.thread;
  btn.disabled = true;
  try {
    const resp = await fetch(`/thread/${encodeURIComponent(conv)}/${encodeURIComponent(ts)}?fragment=1`);
    if (!resp.ok) throw new Error('failed');
    mount.innerHTML = await resp.text();
    mount.dataset.loaded = '1';
    mount.hidden = false;
  } catch (err) {
    mount.innerHTML = '<p class="muted">Could not load thread.</p>';
    mount.hidden = false;
  } finally {
    btn.disabled = false;
  }
});

// 2) On a conversation page opened from a search hit, scroll to the anchored
//    message so the highlighted result is centred.
window.addEventListener('DOMContentLoaded', () => {
  const view = document.querySelector('.conv-view[data-anchor]');
  if (!view) return;
  const anchor = view.dataset.anchor;
  if (!anchor) return;
  const el = document.getElementById('ts-' + anchor);
  if (el) el.scrollIntoView({ block: 'center' });
});
