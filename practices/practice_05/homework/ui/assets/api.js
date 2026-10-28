import {positiveId, sameIds} from './state.js';

export class ProtocolError extends Error {
  constructor(message = 'Ответ сервера не соответствует контракту. Повторите действие явно.') {
    super(message); this.name = 'ProtocolError'; this.confirmed = false;
  }
}
export class APIError extends Error {
  constructor(error, status) {
    super(error.message); this.name = 'APIError'; this.confirmed = true;
    this.code = error.code; this.fields = error.fields; this.status = status;
  }
}
const policy = {
  invalid_request: [400, 405, 415], validation_error: [422], not_found: [404],
  output_conflict: [409], source_error: [502], source_timeout: [504],
  export_failed: [500], internal_error: [500],
};
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const text = value => typeof value === 'string' && value.length > 0;
const natural = value => Number.isSafeInteger(value) && value >= 0;
function requireValue(condition) { if (!condition) throw new ProtocolError(); }
function keys(value, names) {
  requireValue(object(value) && names.every(k => Object.hasOwn(value, k)) && Object.keys(value).every(k => names.includes(k)));
}
export function httpUrl(value, sameOrigin = false) {
  try {
    const url = new URL(value);
    requireValue(text(value) && ['http:', 'https:'].includes(url.protocol) && !url.username && !url.password);
    requireValue(!sameOrigin || url.origin === location.origin);
    return value;
  } catch { throw new ProtocolError('Некорректный адрес ресурса в ответе API.'); }
}
function numbers(value) {
  requireValue(Array.isArray(value) && (sameIds(value, [19, 20, 21]) ||
    (value.length === 1 && positiveId(value[0]) && value[0] <= 27 && ![19, 20, 21].includes(value[0]))));
}
export function validateTask(task) {
  keys(task, ['id', 'ege_numbers', 'statement', 'statement_html', 'source_url', 'listing_url', 'images', 'attachments']);
  requireValue(positiveId(task.id) && text(task.statement) && text(task.statement_html));
  numbers(task.ege_numbers); httpUrl(task.source_url); httpUrl(task.listing_url);
  for (const kind of ['images', 'attachments']) {
    requireValue(Array.isArray(task[kind]));
    task[kind].forEach(url => httpUrl(url, true));
  }
  return task;
}
export function validatePage(value) {
  keys(value, ['requested_ege_number', 'ege_number', 'total', 'offset', 'limit', 'next_offset', 'source_url', 'tasks']);
  requireValue(positiveId(value.requested_ege_number) && value.requested_ege_number <= 27 &&
    positiveId(value.ege_number) && value.ege_number <= 27 && natural(value.total) && natural(value.offset) &&
    positiveId(value.limit) && value.limit <= 30 && (value.next_offset === null || natural(value.next_offset)) &&
    Array.isArray(value.tasks) && value.tasks.length <= value.limit);
  httpUrl(value.source_url); value.tasks.forEach(validateTask);
  requireValue(new Set(value.tasks.map(task => task.id)).size === value.tasks.length);
  return value;
}
function artifact(value, audience, media) {
  keys(value, ['url', 'filename', 'media_type', 'audience']);
  requireValue(value.audience === audience && value.media_type === media && text(value.filename) &&
    !/[\\/\u0000-\u001f]/.test(value.filename));
  httpUrl(value.url, true);
}
export function validateWork(value, ids) {
  keys(value, ['work_id', 'name', 'created_at', 'topic_ids', 'count', 'attachments', 'result', 'pdf', 'archive', 'answers', 'sources']);
  requireValue(typeof value.work_id === 'string' && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value.work_id));
  requireValue(text(value.name) && [...value.name].length <= 80 && text(value.created_at) && Number.isFinite(Date.parse(value.created_at)));
  requireValue(Array.isArray(value.topic_ids) && value.topic_ids.length >= 1 && value.topic_ids.length <= 100 &&
    value.topic_ids.every(positiveId) && new Set(value.topic_ids).size === value.topic_ids.length &&
    value.count === value.topic_ids.length && (!ids || sameIds(value.topic_ids, ids)));
  requireValue(Array.isArray(value.attachments) && value.attachments.every(text));
  const zipped = value.attachments.length > 0;
  artifact(value.result, 'student', zipped ? 'application/zip' : 'application/pdf');
  artifact(value.pdf, 'preview', 'application/pdf');
  artifact(value.answers, 'teacher', 'text/plain; charset=utf-8');
  artifact(value.sources, 'teacher', 'application/json');
  if (zipped) artifact(value.archive, 'student', 'application/zip');
  else requireValue(value.archive === null);
  return value;
}
export async function responseError(response) {
  try {
    requireValue(response.headers.get('content-type')?.split(';')[0].trim() === 'application/json');
    const value = await response.json();
    keys(value, ['error']); keys(value.error, ['code', 'message', 'fields']);
    const error = value.error;
    requireValue(policy[error.code]?.includes(response.status) && text(error.message) && Array.isArray(error.fields));
    error.fields.forEach(field => { keys(field, ['field', 'message']); requireValue(text(field.field) && text(field.message)); });
    return new APIError(error, response.status);
  } catch { return new ProtocolError('Не удалось получить подтверждённый ответ сервера.'); }
}
async function jsonRequest(url, options, expectedStatus) {
  httpUrl(new URL(url, location.origin).href, true);
  const response = await fetch(url, {cache: 'no-store', ...options});
  if (response.status !== expectedStatus) throw await responseError(response);
  try {
    requireValue(response.headers.get('content-type')?.split(';')[0].trim() === 'application/json');
    return await response.json();
  } catch { throw new ProtocolError(); }
}
export async function categories(number, signal) {
  const value = await jsonRequest(`/api/v1/categories?${new URLSearchParams({ege_number: number})}`, {signal}, 200);
  keys(value, ['requested_ege_number', 'ege_number', 'categories']);
  requireValue(value.requested_ege_number === number && value.ege_number === number && Array.isArray(value.categories) && value.categories.length > 0);
  value.categories.forEach(category => { keys(category, ['id', 'title']); requireValue(positiveId(category.id) && text(category.title)); });
  return value.categories;
}
export async function search(number, category, offset, signal) {
  const query = new URLSearchParams({ege_number: number, offset, limit: 10});
  if (category !== null) query.append('category_ids', category);
  const value = validatePage(await jsonRequest(`/api/v1/tasks?${query}`, {signal}, 200));
  requireValue(value.requested_ege_number === number && value.ege_number === number && value.offset === offset && value.limit === 10);
  return value;
}
export async function createWork(ids) {
  requireValue(ids.length >= 1 && ids.length <= 100 && ids.every(positiveId) && new Set(ids).size === ids.length);
  return validateWork(await jsonRequest('/api/v1/works', {method: 'POST', redirect: 'error',
    headers: {'Content-Type': 'application/json'}, body: JSON.stringify({topic_ids: ids})}, 201), ids);
}
export async function getWork(id, ids) {
  const value = validateWork(await jsonRequest(`/api/v1/works/${encodeURIComponent(id)}`, {}, 200), ids);
  requireValue(value.work_id === id);
  return value;
}
export function message(error) {
  if (error instanceof APIError) return [error.message, ...error.fields.map(f => `${f.field}: ${f.message}`)].join(' ');
  if (error instanceof ProtocolError) return error.message;
  return 'Нет связи с API. Проверьте подключение и повторите действие явно.';
}
