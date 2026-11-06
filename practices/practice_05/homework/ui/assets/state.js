export const positiveId = value => Number.isSafeInteger(value) && value > 0;
export const sameIds = (left, right) => left.length === right.length && left.every((id, i) => id === right[i]);

export class Selection {
  constructor() {
    this._ids = [];
    this.tasks = new Map();
    this.revision = 0;
    this.locked = false;
  }
  get ids() { return [...this._ids]; }
  add(task) {
    if (this.locked || !positiveId(task?.id) || this.tasks.has(task.id) || this._ids.length >= 100) return false;
    this._ids.push(task.id);
    this.tasks.set(task.id, task);
    this.revision++;
    return true;
  }
  remove(id) {
    if (this.locked || !this.tasks.has(id)) return false;
    this._ids = this._ids.filter(value => value !== id);
    this.tasks.delete(id);
    this.revision++;
    return true;
  }
  move(id, direction) {
    const index = this._ids.indexOf(id), target = index + direction;
    if (this.locked || ![-1, 1].includes(direction) || index < 0 || target < 0 || target >= this._ids.length) return false;
    [this._ids[index], this._ids[target]] = [this._ids[target], this._ids[index]];
    this.revision++;
    return true;
  }
}

export function createState() {
  const listeners = new Set();
  return {
    selectedEge: null, selectedCategory: null, categories: [], categoriesState: 'idle',
    categoryError: '', searchState: 'idle', searchError: '', page: null,
    previousOffsets: [], pendingNavigation: null, generation: 0,
    selection: new Selection(), exportState: 'idle', exportError: '',
    submittedIds: [], submittedRevision: 0, knownWork: null, metadataBusy: false, metadataMessage: '',
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn); },
    emit() { for (const fn of listeners) fn(this); },
  };
}
export const state = createState();
