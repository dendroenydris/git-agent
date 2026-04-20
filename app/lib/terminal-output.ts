const ANSI_ESCAPE_PATTERN =
  // eslint-disable-next-line no-control-regex
  /\u001B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])/g;

export const TERMINAL_COLLAPSE_CHAR_THRESHOLD = 4000;
export const TERMINAL_COLLAPSE_LINE_THRESHOLD = 24;

export const stripAnsiSequences = (value: string): string => value.replace(ANSI_ESCAPE_PATTERN, '');

export const normalizeTerminalOutput = (value: string | null | undefined): string => {
  const sanitized = stripAnsiSequences(value ?? '').replace(/\r\n/g, '\n');
  let normalized = '';
  let currentLine = '';

  for (const character of sanitized) {
    if (character === '\r') {
      currentLine = '';
      continue;
    }

    if (character === '\n') {
      normalized += `${currentLine}\n`;
      currentLine = '';
      continue;
    }

    currentLine += character;
  }

  return normalized + currentLine;
};

export const appendTerminalChunk = (
  existing: string | null | undefined,
  chunk: string | null | undefined
): string => {
  return normalizeTerminalOutput(`${existing ?? ''}${chunk ?? ''}`);
};

export const shouldCollapseTerminalOutput = (value: string): boolean => {
  if (!value) return false;
  if (value.length > TERMINAL_COLLAPSE_CHAR_THRESHOLD) return true;
  return value.split('\n').length > TERMINAL_COLLAPSE_LINE_THRESHOLD;
};

export const buildTerminalPreview = (value: string): string => {
  const lines = value.split('\n');
  if (lines.length <= TERMINAL_COLLAPSE_LINE_THRESHOLD && value.length <= TERMINAL_COLLAPSE_CHAR_THRESHOLD) {
    return value;
  }

  const previewLines = lines.slice(0, TERMINAL_COLLAPSE_LINE_THRESHOLD).join('\n');
  if (previewLines.length >= TERMINAL_COLLAPSE_CHAR_THRESHOLD) {
    return `${previewLines.slice(0, TERMINAL_COLLAPSE_CHAR_THRESHOLD)}\n...`;
  }

  return `${previewLines}\n...`;
};
