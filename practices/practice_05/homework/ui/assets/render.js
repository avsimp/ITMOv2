import {sameIds} from './state.js';

export const $ = id => document.getElementById(id);
export function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}
const group = task => task.ege_numbers?.length === 3 ? '19–21' : task.ege_numbers?.join(', ');
let selectionRevision = -1, selectionLocked = null, workId = null;

export function renderResults(page, onResources) {
  $('results').replaceChildren();
  for (const task of page.tasks) {
    const card = element('article', undefined, 'task-card');
    card.dataset.taskId = task.id;
    card.dataset.resources = task.images.length ? 'pending' : 'ready';
    const header = element('div', undefined, 'task-heading');
    header.append(element('h3', `ЕГЭ ${group(task)} · ID ${task.id}`),
      element('span', task.attachments.length ? 'Есть приложения' : 'Без приложений', 'task-meta'));
    const statement = element('div', undefined, 'statement');
    // Contract 1.0.0: only the API's allowlisted browser projection belongs here.
    // Other strings (including API errors) are always textContent.
    statement.innerHTML = task.statement_html;
    const resourceStatus = element('p', '', 'resource-status');
    const retry = element('button', 'Повторить загрузку рисунков', 'secondary');
    retry.type = 'button'; retry.hidden = true;
    const failed = new Set(), pending = new Set(statement.querySelectorAll('img'));
    function update() {
      card.dataset.resources = failed.size ? 'error' : pending.size ? 'pending' : 'ready';
      resourceStatus.textContent = failed.size ? 'Рисунок не загружен. Условие отображено не полностью.' : pending.size ? 'Загружаем рисунки…' : '';
      retry.hidden = !failed.size;
      onResources();
    }
    for (const image of pending) {
      image.addEventListener('load', () => { pending.delete(image); failed.delete(image); update(); });
      image.addEventListener('error', () => { pending.delete(image); failed.add(image); update(); });
      if (image.complete) {
        pending.delete(image);
        if (!image.naturalWidth) failed.add(image);
      }
    }
    retry.addEventListener('click', () => {
      for (const image of [...failed]) {
        failed.delete(image); pending.add(image);
        const src = image.getAttribute('src'); image.removeAttribute('src'); image.setAttribute('src', src);
      }
      update();
    });
    const actions = element('div', undefined, 'task-actions');
    const source = element('a', 'Оригинал на сайте');
    source.href = task.source_url; source.target = '_blank'; source.rel = 'noopener';
    const add = element('button', 'Добавить', 'add-task');
    add.type = 'button'; add.dataset.action = 'add'; add.dataset.id = task.id;
    actions.append(source, add);
    card.append(header, statement, resourceStatus, retry, actions);
    $('results').append(card); update();
  }
}

function renderSelection(state) {
  const selection = state.selection;
  if (selectionRevision === selection.revision && selectionLocked === selection.locked) return;
  selectionRevision = selection.revision; selectionLocked = selection.locked;
  const focused = document.activeElement;
  const wasSelectionFocused = !!focused?.closest('#selection');
  const focusId = Number(focused?.dataset.id), focusAction = focused?.dataset.action;
  const oldRowIndex = selection.ids.indexOf(focusId);
  $('selection').replaceChildren();
  const ids = selection.ids;
  ids.forEach((id, index) => {
    const task = selection.tasks.get(id), row = element('li'); row.dataset.taskId = id;
    row.append(element('div', `${index + 1}) ЕГЭ ${group(task)} · ID ${id}`, 'selection-title'),
      element('p', task.statement.slice(0, 140) + (task.statement.length > 140 ? '…' : ''), 'selection-text'));
    const actions = element('div', undefined, 'selection-actions');
    for (const [action, label, unavailable] of [['up', 'Вверх', index === 0], ['down', 'Вниз', index === ids.length - 1], ['remove', 'Удалить', false]]) {
      const button = element('button', label, 'secondary'); button.type = 'button';
      button.dataset.action = action; button.dataset.id = id;
      button.disabled = selection.locked || unavailable; actions.append(button);
    }
    row.append(actions); $('selection').append(row);
  });
  if (focusAction && wasSelectionFocused) {
    const target = $('selection').querySelector(`[data-id="${focusId}"][data-action="${focusAction}"]:not(:disabled)`)
      || $('selection').querySelector(`li:nth-child(${Math.max(1, oldRowIndex + 1)}) button:not(:disabled)`)
      || $('selection').querySelector('button:not(:disabled)');
    (target || $('create-work')).focus();
  }
}

export function syncAddButtons(state) {
  document.querySelectorAll('.add-task').forEach(button => {
    const selected = state.selection.tasks.has(Number(button.dataset.id));
    button.textContent = selected ? 'В подборке' : 'Добавить';
    button.disabled = selected || state.selection.locked || state.selection.ids.length >= 100 ||
      state.searchState !== 'ready' || button.closest('.task-card').dataset.resources !== 'ready';
  });
}

export function renderWork(state) {
  const work = state.knownWork;
  $('work-result').hidden = !work;
  if (!work) return;
  $('work-name').textContent = work.name;
  $('work-count').textContent = `Пунктов: ${work.count} · ID работы: ${work.work_id}`;
  $('work-version').textContent = sameIds(state.selection.ids, work.topic_ids) ? 'Материалы соответствуют текущей подборке.' : 'Для предыдущей подборки. Создайте новую работу после изменений.';
  $('zip-hint').hidden = work.result.media_type !== 'application/zip';
  $('refresh-work').disabled = state.metadataBusy;
  $('metadata-status').textContent = state.metadataMessage;
  if (workId === work.work_id) return;
  workId = work.work_id;
  $('materials').replaceChildren();
  const zipped = work.result.media_type === 'application/zip';
  for (const [kind, label] of [['result', `Скачать для ученика (${zipped ? 'ZIP' : 'PDF'})`],
    ['answers', 'Скачать ответы · Для преподавателя'], ['sources', 'Скачать источники · Для преподавателя']]) {
    const button = element('button', label, kind === 'result' ? '' : 'secondary');
    button.type = 'button'; button.dataset.download = kind;
    $('materials').append(button);
  }
  $('preview-pdf').href = work.pdf.url; $('preview-pdf').hidden = !zipped;
}

export function render(state) {
  const count = state.selection.ids.length;
  $('selection-count').textContent = `${count} / 100`;
  $('selection-empty').hidden = count > 0; $('selection-limit').hidden = count < 100;
  $('category').disabled = state.categoriesState !== 'ready';
  $('search-button').disabled = state.categoriesState !== 'ready' || state.searchState === 'loading';
  $('retry-categories').hidden = state.categoriesState !== 'error';
  $('retry-search').hidden = state.searchState !== 'error';
  $('previous-page').disabled = state.searchState === 'loading' || !state.previousOffsets.length;
  $('next-page').disabled = state.searchState === 'loading' || !state.page || state.page.next_offset === null;
  const status = $('search-status');
  status.dataset.state = state.searchState;
  status.textContent = state.categoriesState === 'loading' ? 'Загружаем категории…' :
    state.categoriesState === 'error' ? state.categoryError :
    ({idle: 'Выберите фильтр и нажмите «Найти задачи».', loading: 'Ищем задачи…',
      empty: state.page?.total ? 'На этой странице задач нет. Вернитесь назад или начните поиск сначала.' : 'Ничего не найдено. Попробуйте изменить фильтры.',
      error: state.searchError, ready: `Найдено задач: ${state.page?.total}.`})[state.searchState];
  if (!state.selectedEge) status.textContent = 'Выберите номер ЕГЭ, чтобы начать поиск.';
  const page = state.page;
  $('page-range').textContent = page ? `Показано ${page.tasks.length ? page.offset + 1 : 0}–${page.offset + page.tasks.length} из ${page.total}` : 'Поиск ещё не выполнен';
  $('results').hidden = state.searchState !== 'ready';
  $('results').setAttribute('aria-busy', String(state.searchState === 'loading'));
  $('create-work').disabled = !count || state.exportState === 'pending';
  $('create-work').textContent = state.exportState === 'unknown' ? 'Создать новую работу' : 'Создать работу';
  $('export-status').dataset.state = state.exportState;
  $('export-status').textContent = ({idle: count ? 'Имя назначит сервер. Порядок пунктов сохранится.' : 'Добавьте хотя бы одну задачу.',
    pending: 'Создаём работу… Дождитесь завершения запроса.', succeeded: 'Работа создана. Материалы готовы к скачиванию.',
    failed: `Создание отклонено. ${state.exportError}`, unknown: 'Результат не подтверждён. Предыдущая работа могла быть создана. Автоматического повтора нет. «Создать новую работу» создаст отдельную работу; возможен дубль содержимого.'})[state.exportState];
  renderSelection(state); syncAddButtons(state); renderWork(state);
}

export function renderDownload(value) {
  const status = $('download-status');
  if (value.phase) {
    status.dataset.state = value.phase;
    status.textContent = value.message;
    $('save-file').hidden = value.phase !== 'ready';
    if (value.ready) {
      $('save-file').href = value.ready.url;
      $('save-file').download = value.ready.filename;
      $('save-file').textContent = `Сохранить файл · ${value.ready.filename}`;
    } else { $('save-file').removeAttribute('href'); }
  }
  document.querySelectorAll('[data-download]').forEach(button => {
    const work = button.dataset.url;
    button.disabled = !!work && value.busy.has(work);
  });
}
