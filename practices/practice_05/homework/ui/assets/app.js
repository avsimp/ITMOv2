import * as api from './api.js';
import {state} from './state.js';
import {$, element, render, renderResults, syncAddButtons, renderDownload} from './render.js';
import {Downloads} from './downloads.js';

let categoryGeneration = 0, categoryController = null, searchController = null;
const downloads = new Downloads(renderDownload);
state.subscribe(render);
for (let number = 1; number <= 27; number++) {
  if (number === 20 || number === 21) continue;
  const option = element('option', number === 19 ? '19–21 · один блок' : String(number));
  option.value = number; $('ege-number').append(option);
}

function clearSearch() {
  state.generation++;
  searchController?.abort();
  state.searchState = 'idle'; state.searchError = ''; state.page = null;
  state.previousOffsets = []; state.pendingNavigation = null;
  $('results').replaceChildren();
}
async function loadCategories() {
  const generation = ++categoryGeneration, number = state.selectedEge;
  categoryController?.abort(); categoryController = new AbortController();
  state.categoriesState = number ? 'loading' : 'idle'; state.categoryError = '';
  state.categories = []; state.selectedCategory = null;
  const all = element('option', 'Все категории'); all.value = '';
  $('category').replaceChildren(all); state.emit();
  if (!number) return;
  try {
    const values = await api.categories(number, categoryController.signal);
    if (generation !== categoryGeneration) return;
    state.categories = values; state.categoriesState = 'ready';
    for (const category of values) {
      const option = element('option', category.title); option.value = category.id; $('category').append(option);
    }
  } catch (error) {
    if (generation !== categoryGeneration) return;
    state.categoriesState = 'error'; state.categoryError = api.message(error);
  }
  if (generation === categoryGeneration) state.emit();
}
async function find(offset = 0, direction = 'new') {
  if (state.categoriesState !== 'ready' || state.searchState === 'loading') return;
  const generation = ++state.generation, number = state.selectedEge, category = state.selectedCategory;
  searchController?.abort(); searchController = new AbortController();
  if (direction === 'new') state.previousOffsets = [];
  state.pendingNavigation = {offset, direction}; state.searchState = 'loading'; state.searchError = ''; state.emit();
  try {
    const result = await api.search(number, category, offset, searchController.signal);
    if (generation !== state.generation) return;
    if (direction === 'next' && state.page) state.previousOffsets.push(state.page.offset);
    if (direction === 'previous') state.previousOffsets.pop();
    state.page = result; state.searchState = result.tasks.length ? 'ready' : 'empty';
    renderResults(result, () => syncAddButtons(state));
  } catch (error) {
    if (generation !== state.generation) return;
    state.searchState = 'error'; state.searchError = api.message(error);
  }
  if (generation === state.generation) state.emit();
}

$('ege-number').addEventListener('change', () => {
  state.selectedEge = $('ege-number').value ? Number($('ege-number').value) : null;
  clearSearch(); loadCategories();
});
$('category').addEventListener('change', () => {
  state.selectedCategory = $('category').value ? Number($('category').value) : null;
  clearSearch(); state.emit();
});
$('search-form').addEventListener('submit', event => { event.preventDefault(); find(); });
$('retry-categories').addEventListener('click', loadCategories);
$('retry-search').addEventListener('click', () => {
  const nav = state.pendingNavigation;
  find(nav?.offset || 0, nav?.direction || 'new');
});
$('next-page').addEventListener('click', () => {
  if (state.page?.next_offset !== null && state.page) find(state.page.next_offset, 'next');
});
$('previous-page').addEventListener('click', () => {
  if (state.previousOffsets.length) find(state.previousOffsets.at(-1), 'previous');
});
$('results').addEventListener('click', event => {
  const button = event.target.closest('.add-task');
  if (!button || button.disabled || state.searchState !== 'ready') return;
  const task = state.page.tasks.find(task => task.id === Number(button.dataset.id));
  if (task && state.selection.add(task)) state.emit();
});
$('selection').addEventListener('click', event => {
  const button = event.target.closest('button');
  if (!button || button.disabled) return;
  const id = Number(button.dataset.id), action = button.dataset.action;
  const changed = action === 'remove' ? state.selection.remove(id) : state.selection.move(id, action === 'up' ? -1 : 1);
  if (changed) state.emit();
});
$('create-work').addEventListener('click', async () => {
  if (state.exportState === 'pending' || !state.selection.ids.length) return;
  state.submittedIds = state.selection.ids;
  state.submittedRevision = state.selection.revision;
  const ids = [...state.submittedIds];
  state.exportState = 'pending'; state.exportError = ''; state.selection.locked = true; state.emit();
  try {
    const work = await api.createWork(ids);
    state.knownWork = work; state.exportState = 'succeeded'; state.metadataMessage = '';
    downloads.reset();
  } catch (error) {
    state.exportState = error.confirmed ? 'failed' : 'unknown';
    state.exportError = api.message(error);
  } finally {
    state.selection.locked = false; state.emit();
  }
});
$('materials').addEventListener('click', event => {
  const button = event.target.closest('[data-download]');
  if (!button || button.disabled || !state.knownWork) return;
  const artifact = state.knownWork[button.dataset.download];
  button.dataset.url = artifact.url;
  downloads.get(artifact);
});
$('refresh-work').addEventListener('click', async () => {
  if (!state.knownWork || state.metadataBusy) return;
  const work = state.knownWork;
  state.metadataBusy = true; state.metadataMessage = 'Обновляем сведения…'; state.emit();
  try {
    const updated = await api.getWork(work.work_id, work.topic_ids);
    if (state.knownWork?.work_id === work.work_id) {
      state.knownWork = updated; state.metadataMessage = 'Сведения о работе обновлены.';
    }
  } catch (error) {
    if (state.knownWork?.work_id === work.work_id) state.metadataMessage = api.message(error);
  } finally { state.metadataBusy = false; state.emit(); }
});
window.addEventListener('pagehide', () => downloads.reset());
state.emit();
