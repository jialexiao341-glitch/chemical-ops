/** 增量 SSE 分帧，支持 LF/CRLF、多行 data 和 EOF 末帧。 */
export function createSseParser(onEvent: (event: string, data: string) => void) {
  let buffer = '';
  function emit(frame: string) {
    let event = 'message';
    const data: string[] = [];
    for (const line of frame.split(/\r?\n/)) {
      if (line.startsWith('event:')) event = line.slice(6).trim();
      if (line.startsWith('data:')) data.push(line.slice(5).replace(/^ /, ''));
    }
    if (data.length) onEvent(event, data.join('\n'));
  }
  return (chunk: string, end = false) => {
    buffer += chunk;
    let separator = /\r?\n\r?\n/.exec(buffer);
    while (separator) {
      emit(buffer.slice(0, separator.index));
      buffer = buffer.slice(separator.index + separator[0].length);
      separator = /\r?\n\r?\n/.exec(buffer);
    }
    if (end && buffer) { emit(buffer); buffer = ''; }
  };
}
