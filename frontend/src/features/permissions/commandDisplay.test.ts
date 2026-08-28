import { describe, expect, it } from 'vitest'

import { formatCommandArguments, quoteCommandArgument } from './commandDisplay'

describe('command approval display', () => {
  it('keeps every argv boundary visible with JSON-style quoting', () => {
    expect(formatCommandArguments(['python', 'file with spaces.py', '--name="demo"'])).toBe(
      '[\n  "python",\n  "file with spaces.py",\n  "--name=\\"demo\\""\n]',
    )
  })

  it('renders line breaks, tabs, nulls and control bytes as text escapes', () => {
    const displayed = quoteCommandArgument('line1\nline2\t\r\0\u007f\u0085')
    expect(displayed).toBe('"line1\\nline2\\t\\r\\u0000\\u007f\\u0085"')
    expect(displayed).not.toMatch(/[\u0000-\u001f\u007f-\u009f]/u)
  })

  it('escapes invisible direction and line-separator controls', () => {
    expect(quoteCommandArgument('safe\u202eevil\u2028next\u2066end')).toBe(
      '"safe\\u202eevil\\u2028next\\u2066end"',
    )
  })

  it('escapes slashes and handles empty argument lists explicitly', () => {
    expect(quoteCommandArgument('C:\\work\\file')).toBe('"C:\\\\work\\\\file"')
    expect(formatCommandArguments([])).toBe('[]')
  })
})
