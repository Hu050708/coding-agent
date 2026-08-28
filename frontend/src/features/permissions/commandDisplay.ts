function unicodeEscape(codePoint: number): string {
  if (codePoint <= 0xffff) return `\\u${codePoint.toString(16).padStart(4, '0')}`
  const offset = codePoint - 0x10000
  const high = 0xd800 + (offset >> 10)
  const low = 0xdc00 + (offset & 0x3ff)
  return `\\u${high.toString(16)}\\u${low.toString(16)}`
}

function mustEscapeFormattingCharacter(codePoint: number): boolean {
  return (
    codePoint <= 0x1f ||
    (codePoint >= 0x7f && codePoint <= 0x9f) ||
    (codePoint >= 0x200b && codePoint <= 0x200f) ||
    (codePoint >= 0x2028 && codePoint <= 0x202e) ||
    codePoint === 0x2060 ||
    (codePoint >= 0x2066 && codePoint <= 0x2069) ||
    codePoint === 0xfeff
  )
}

/**
 * Quotes one argv item without changing its boundary. Besides JSON's usual
 * escapes, formatting and bidirectional controls are made visible so an
 * argument cannot forge extra lines or visually reorder neighboring text.
 */
export function quoteCommandArgument(value: string): string {
  let result = '"'
  for (const character of value) {
    const codePoint = character.codePointAt(0) ?? 0
    if (character === '"') result += '\\"'
    else if (character === '\\') result += '\\\\'
    else if (character === '\b') result += '\\b'
    else if (character === '\f') result += '\\f'
    else if (character === '\n') result += '\\n'
    else if (character === '\r') result += '\\r'
    else if (character === '\t') result += '\\t'
    else if (mustEscapeFormattingCharacter(codePoint)) result += unicodeEscape(codePoint)
    else result += character
  }
  return `${result}"`
}

export function formatCommandArguments(argv: readonly string[]): string {
  if (argv.length === 0) return '[]'
  return `[\n${argv.map((argument) => `  ${quoteCommandArgument(argument)}`).join(',\n')}\n]`
}
