(() => {
  const input = document.querySelector('#report-search');
  if (!input) return;
  const buttons = [...document.querySelectorAll('[data-kind]')];
  const reports = [...document.querySelectorAll('[data-report-kind]')];
  const status = document.querySelector('#filter-status');
  let selected = 'all';
  function filter() {
    const query = input.value.trim().toLocaleLowerCase();
    let visible = 0;
    for (const report of reports) {
      const matches = (selected === 'all' || report.dataset.reportKind === selected)
        && report.textContent.toLocaleLowerCase().includes(query);
      report.hidden = !matches;
      if (matches) visible += 1;
    }
    status.textContent = visible + (visible === 1 ? ' report' : ' reports');
    document.querySelector('#no-results').hidden = visible !== 0;
  }
  input.addEventListener('input', filter);
  for (const button of buttons) {
    button.addEventListener('click', () => {
      selected = button.dataset.kind;
      for (const peer of buttons) peer.setAttribute('aria-pressed', String(peer === button));
      filter();
    });
  }
  filter();
})();
