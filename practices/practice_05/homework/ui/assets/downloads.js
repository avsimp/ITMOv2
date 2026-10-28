import {httpUrl, responseError, ProtocolError, message} from './api.js';

export class Downloads {
  constructor(onChange) { this.onChange = onChange; this.busy = new Set(); this.serial = 0; this.ready = null; }
  reset() {
    this.serial++;
    if (this.ready) URL.revokeObjectURL(this.ready.url);
    this.ready = null;
    this.onChange({phase: 'idle', message: '', busy: this.busy});
  }
  async get(artifact) {
    if (this.busy.has(artifact.url)) return;
    const serial = ++this.serial;
    this.busy.add(artifact.url);
    this.onChange({phase: 'loading', message: `Получаем ${artifact.filename}…`, busy: this.busy});
    try {
      httpUrl(artifact.url, true);
      const response = await fetch(artifact.url, {cache: 'no-store', redirect: 'error'});
      if (response.status !== 200) {
        if ([206, 416].includes(response.status) ||
          (response.status === 400 && !response.headers.get('content-type')?.includes('application/json'))) {
          throw new ProtocolError('Файл не получен целиком. Повторите скачивание без нового создания работы.');
        }
        throw await responseError(response);
      }
      const mime = response.headers.get('content-type')?.split(';')[0].trim().toLowerCase();
      if (mime !== artifact.media_type.split(';')[0]) throw new ProtocolError('Неверный тип скачиваемого файла.');
      const blob = await response.blob();
      const length = response.headers.get('content-length');
      if (length !== null && !response.headers.has('content-encoding') && Number(length) !== blob.size) {
        throw new ProtocolError('Передача файла прервалась. Повторите скачивание.');
      }
      if (serial !== this.serial) return;
      if (this.ready) URL.revokeObjectURL(this.ready.url);
      this.ready = {url: URL.createObjectURL(blob), filename: artifact.filename};
      this.onChange({phase: 'ready', message: 'Файл получен. Нажмите «Сохранить файл», чтобы сохранить его на компьютере.', ready: this.ready, busy: this.busy});
    } catch (error) {
      if (serial === this.serial) this.onChange({phase: 'error', message: message(error), busy: this.busy});
    } finally {
      this.busy.delete(artifact.url);
      // Update only busy buttons; preserve the current ready/error announcement.
      this.onChange({busy: this.busy});
    }
  }
}
