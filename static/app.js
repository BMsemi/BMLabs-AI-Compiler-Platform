(() => {
  const root = document.documentElement;
  const menu = document.querySelector('[data-menu]');
  const sidebar = document.querySelector('#sidebar');
  const shell = document.querySelector('.app-shell');
  const mobile = window.matchMedia('(max-width: 900px)');
  function save(key, value) { try { localStorage.setItem(key, value); } catch {} }
  function syncMenu() {
    const open = document.body.classList.contains('menu-open');
    menu?.setAttribute('aria-expanded', String(mobile.matches ? open : root.dataset.sidebar !== 'collapsed'));
    if (sidebar) sidebar.inert = mobile.matches && !open;
    if (shell) shell.inert = mobile.matches && open;
  }
  function closeMenu() {
    document.body.classList.remove('menu-open');
    syncMenu();
    menu?.focus();
  }
  menu?.addEventListener('click', () => {
    if (mobile.matches) {
      document.body.classList.toggle('menu-open');
      syncMenu();
      sidebar?.querySelector('[data-menu-close]')?.focus();
    } else {
      root.dataset.sidebar = root.dataset.sidebar === 'collapsed' ? 'expanded' : 'collapsed';
      save('bmlabs-sidebar', root.dataset.sidebar);
      syncMenu();
    }
  });
  document.querySelectorAll('[data-menu-close]').forEach(button => button.addEventListener('click', closeMenu));
  mobile.addEventListener('change', () => { document.body.classList.remove('menu-open'); syncMenu(); });
  syncMenu();
  const themeToggle = document.querySelector('[data-theme-toggle]');
  const updateThemeLabel = () => themeToggle?.setAttribute('aria-label', `Switch to ${root.dataset.theme === 'light' ? 'dark' : 'light'} theme`);
  updateThemeLabel();
  themeToggle?.addEventListener('click', () => {
    root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
    save('bmlabs-theme', root.dataset.theme);
    updateThemeLabel();
  });
  document.querySelectorAll('.sidebar nav a.selected').forEach(link => link.setAttribute('aria-current', 'page'));
  document.querySelectorAll('form[data-confirm]').forEach(form => form.addEventListener('submit', event => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  }));
  document.querySelector('[data-project-picker]')?.addEventListener('submit', event => {
    event.preventDefault();
    const value = event.currentTarget.querySelector('select').value;
    if (value.startsWith('/projects/')) window.location.assign(value);
  });
  const dialog = document.querySelector('#command-dialog');
  const input = document.querySelector('#command-input');
  const results = document.querySelector('#command-results');
  const empty = document.querySelector('.command-empty');
  let index = 0;
  let opener;
  const pages = [...document.querySelectorAll('[data-nav]')].map(link => ({title: link.title || link.textContent.trim(), href: link.getAttribute('href'), icon: link.querySelector('svg')?.cloneNode(true)}));
  function activate(next) {
    const links = [...results.querySelectorAll('a')];
    index = links.length ? (next + links.length) % links.length : 0;
    links.forEach((link, i) => link.classList.toggle('command-active', i === index));
    links[index]?.scrollIntoView({block:'nearest'});
  }
  function renderResults() {
    results.replaceChildren();
    const filtered = pages.filter(page => page.title.toLowerCase().includes(input.value.trim().toLowerCase()));
    filtered.forEach(page => {
      const link = document.createElement('a');
      link.href = page.href;
      if (page.icon) link.append(page.icon.cloneNode(true));
      const label = document.createElement('span');
      label.textContent = page.title;
      link.append(label);
      const enter = document.createElement('span');
      enter.className = 'command-enter';
      enter.textContent = '↵';
      enter.setAttribute('aria-hidden', 'true');
      link.append(enter);
      results.append(link);
    });
    empty.hidden = filtered.length > 0;
    activate(0);
  }
  function openCommand() {
    if (!dialog || dialog.open) return;
    opener = document.activeElement;
    input.value = '';
    renderResults();
    dialog.showModal();
    input.focus();
  }
  document.querySelectorAll('[data-command-open]').forEach(button => button.addEventListener('click', openCommand));
  document.querySelector('[data-command-close]')?.addEventListener('click', () => dialog.close());
  dialog?.addEventListener('close', () => opener?.focus());
  dialog?.addEventListener('click', event => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); } });
  input?.addEventListener('input', renderResults);
  input?.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') { event.preventDefault(); activate(index + (event.key === 'ArrowDown' ? 1 : -1)); }
    if (event.key === 'Enter') { event.preventDefault(); results.querySelectorAll('a')[index]?.click(); }
  });
  document.addEventListener('keydown', event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); openCommand(); }
    if (event.key === 'Escape' && document.body.classList.contains('menu-open') && !dialog?.open) closeMenu();
    if (event.key === 'Tab' && mobile.matches && document.body.classList.contains('menu-open') && !dialog?.open) {
      const focusable = [...sidebar.querySelectorAll('a,button')].filter(el => el.offsetParent !== null);
      if (event.shiftKey && document.activeElement === focusable[0]) { event.preventDefault(); focusable.at(-1)?.focus(); }
      if (!event.shiftKey && document.activeElement === focusable.at(-1)) { event.preventDefault(); focusable[0]?.focus(); }
    }
  });
  document.querySelector('#api-explorer')?.addEventListener('submit', async event => {
    event.preventDefault();
    const output = document.querySelector('#api-response');
    const button = event.currentTarget.querySelector('button');
    button.disabled = true;
    output.textContent = 'Loading…';
    try {
      const response = await fetch(document.querySelector('#endpoint').value, {headers:{Accept:'application/json'}, credentials:'same-origin'});
      output.textContent = `HTTP ${response.status}\n\n${JSON.stringify(await response.json(), null, 2)}`;
    } catch { output.textContent = 'Request failed. Check your connection and sign-in session.'; }
    finally { button.disabled = false; }
  });
})();
