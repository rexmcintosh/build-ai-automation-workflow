'use strict';
const $ = (id) => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
let snapshot;
let selected;
const el = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = text; return node; };
const add = (parent, ...children) => { children.forEach(child => parent.append(child)); return parent; };
const fmt = (value) => value ? new Date(value).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'Not observed';
const number = (value) => new Intl.NumberFormat(undefined, { notation: 'compact', maximumFractionDigits: 1 }).format(value || 0);
const badge = (status) => el('span', `badge ${String(status).toLowerCase().replace(/[^a-z_]/g, '-')}`, String(status).replaceAll('_', ' '));
function link(url, label) {
  if (!url || !(url.startsWith('https://') || url.startsWith('http://') || /^\/decisions\/[a-zA-Z0-9_.-]+$/.test(url))) return el('span', 'muted', label);
  const a = el('a', 'text-link', label); a.href = url;
  if (url.startsWith('http')) { a.target = '_blank'; a.rel = 'noopener noreferrer'; }
  return a;
}
function render() {
  $('date').textContent = new Date(snapshot.generated_at).toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
  $('mode').textContent = snapshot.mode;
  $('freshness').textContent = `Read at ${fmt(snapshot.generated_at)}. Evidence dates are shown below.`;
  $('decisions').replaceChildren(...snapshot.decisions.map(d => {
    const row = el('article', 'decision');
    add(row, el('p', 'decision-initiative', d.initiative), el('h3', '', d.title), el('p', 'decision-recommendation', d.recommendation));
    add(row, el('p', 'decision-why', d.why), el('p', 'muted', `${d.horizon} · Evidence: ${fmt(d.observed_at)}`));
    add(row, link(d.source_url, 'Read the decision case'), badge('proposed'));
    return row;
  }));
  if (!snapshot.decisions.length) $('decisions').append(el('p', 'coverage', 'No prepared decision cases are connected. This does not establish that no decisions are needed.'));
  $('initiative-list').replaceChildren(...snapshot.initiatives.map(i => {
    const row = el('article', 'initiative');
    const heading = add(el('div', 'initiative-heading'), el('h3', '', i.name), badge(i.assessment || 'unassessed'));
    const intent = add(el('div', 'initiative-intent'), el('p', '', i.purpose || 'The current Ideal State has not been linked.'), i.ideal_url ? link(i.ideal_url, 'Ideal State') : el('small', '', 'No verified Ideal State link connected'));
    const evidence = add(el('div', 'initiative-evidence'), el('p', '', i.evidence || 'Outcome evidence is not connected.'), el('small', '', `Evidence as of ${fmt(i.observed_at)}`));
    const count = snapshot.work.filter(w => (i.repos || []).includes(w.repo)).length;
    add(row, heading, intent, evidence, el('p', 'initiative-count', `${count} work item${count === 1 ? '' : 's'}`));
    return row;
  }));
  renderWork();
  $('sources').replaceChildren(...snapshot.sources.map(s => add(el('article', 'source-row'),
    add(el('div', ''), el('h3', '', s.name), el('p', '', s.detail)), badge(s.status), el('small', '', `Source updated: ${fmt(s.updated_at)}`))));
  const notes = [...snapshot.coverage_notes];
  if (snapshot.unmapped_repositories.length) notes.push(`Work without a linked initiative: ${snapshot.unmapped_repositories.join(', ')}.`);
  $('coverage').replaceChildren(el('h3', '', 'Coverage still to close'), ...notes.map(note => el('p', '', note)));
  const resources = snapshot.resources;
  const summary = add(el('div', 'resource-summary'),
    add(el('div', ''), el('h3', '', 'Cash and allocation'), el('p', '', 'Not yet reconciled'), el('small', '', 'Unknown is not zero.')),
    add(el('div', ''), el('h3', '', 'Owner time'), el('p', '', '€75/hour, nominal'), el('small', '', 'No saved hours or cash benefit claimed.')),
    add(el('div', ''), el('h3', '', 'Morning review'), el('p', '', 'One hour, aspirational'), el('small', '', 'Necessary work remains visible.')));
  const usage = el('div', 'usage');
  add(usage, el('h3', '', 'Recorded model use, last seven days'), el('p', 'muted', resources.detail));
  for (const u of resources.usage) add(usage, add(el('div', 'usage-row'), el('span', '', u.project), el('span', '', `${number(u.calls)} calls`), el('span', '', `${number(u.tokens_in)} input tokens`), el('span', '', `${number(u.tokens_out)} output tokens`)));
  if (!resources.usage.length) usage.append(el('p', '', 'No usage rows are available in this view.'));
  $('resource-view').replaceChildren(summary, usage);
}
function renderWork() {
  const query = $('filter').value.trim().toLowerCase();
  const rows = snapshot.work.filter(w => [w.title, w.repo, w.why, w.status].join(' ').toLowerCase().includes(query));
  $('work-count').textContent = `${snapshot.work.length} items across connected sources`;
  $('work-list').replaceChildren(...rows.map(w => {
    const row = el('details', 'work-row');
    const summary = add(el('summary', ''), el('span', 'work-title', w.title), el('span', 'work-repo', w.repo), badge(w.status));
    const detail = add(el('div', 'work-detail'), el('p', '', w.why), el('small', '', `${w.source} · Created ${fmt(w.created)} · ${w.id}`));
    if (w.owner_surface_status) detail.append(el('p', '', `Owner queue: ${w.owner_surface_status}`));
    if (w.source_url) detail.append(link(w.source_url, 'Open the source'));
    if (w.hold_token) {
      const button = el('button', 'quiet', 'Hold this work');
      button.addEventListener('click', () => { selected = w; $('hold-title').textContent = w.title; $('hold-reason').value = ''; $('hold-error').textContent = ''; $('hold-dialog').showModal(); $('hold-reason').focus(); });
      detail.append(button);
    }
    return add(row, summary, detail);
  }));
  $('empty').hidden = rows.length > 0;
}
async function refresh() {
  $('refresh').disabled = true; $('error').hidden = true;
  try {
    const response = await fetch('/api/snapshot', { cache: 'no-store' });
    if (response.status === 401) { location.assign('/login'); return; }
    if (!response.ok) throw new Error('The portfolio could not refresh. The previous view may be stale. Try again.');
    snapshot = await response.json(); render(); $('content').hidden = false;
  } catch (error) { $('error').textContent = error.message; $('error').hidden = false; }
  finally { $('loading').hidden = true; $('refresh').disabled = false; }
}
$('refresh').addEventListener('click', refresh);
$('filter').addEventListener('input', () => { if (snapshot) renderWork(); });
$('cancel-hold').addEventListener('click', () => $('hold-dialog').close());
$('hold-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const button = event.submitter; button.disabled = true;
  try {
    const response = await fetch(`/api/work/${encodeURIComponent(selected.id)}/hold`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf }, body: JSON.stringify({ token: selected.hold_token, reason: $('hold-reason').value }) });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || 'The result is uncertain. Refresh before trying again.');
    $('hold-dialog').close(); await refresh();
  } catch (error) { $('hold-error').textContent = error.message; }
  finally { button.disabled = false; }
});
refresh();
