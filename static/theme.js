(() => {
  try {
    const saved = localStorage.getItem('bmlabs-theme');
    document.documentElement.dataset.theme = saved === 'light' ? 'light' : 'dark';
    if (localStorage.getItem('bmlabs-sidebar') === 'collapsed') document.documentElement.dataset.sidebar = 'collapsed';
  } catch { document.documentElement.dataset.theme = 'dark'; }
})();
