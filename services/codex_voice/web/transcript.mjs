/** Frameless voice emits timed word fragments, each with its own item id. */
export class TranscriptAssembler {
  constructor() {
    this.seen = new Set();
    this.serial = 0;
    this.role = null;
    this.text = '';
  }

  push(message) {
    if (['turn.done', 'turn.completed', 'turn.cancelled'].includes(message.type)) {
      this.role = null;
      return null;
    }
    if (!['input_transcript.added', 'output_transcript.added'].includes(message.type)) return null;
    const text = message.item?.text;
    if (typeof text !== 'string' || !text) return null;
    const id = message.item?.id;
    if (id && this.seen.has(id)) return null;
    if (id) this.seen.add(id);
    if (this.seen.size > 1000) this.seen.delete(this.seen.values().next().value);
    const role = message.type.startsWith('input') ? 'user' : 'assistant';
    if (role !== this.role) {
      this.serial += 1;
      this.text = '';
      this.role = role;
    }
    this.text += text;
    return { role, key: 'speech-' + this.serial, text: this.text.trim() };
  }
}
