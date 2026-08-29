import { describe, expect, it } from 'vitest'

import { demoSteps, type JsonObject } from './workflow'

describe('fixed workflow demo', () => {
  it('keeps the file, command output, and final run state across snapshots', () => {
    expect(demoSteps).toHaveLength(10)

    const fileStep = demoSteps[4]!.state.workspace as JsonObject
    const files = fileStep.files as JsonObject[]
    expect(files[0]?.path).toBe('hello.py')
    expect(files[0]?.content).toContain('Hello, world!')

    const commandStep = demoSteps[7]!.state.workspace as JsonObject
    const command = commandStep.last_command as JsonObject
    expect(command.exit_code).toBe(0)
    expect(command.stdout).toBe('Hello, world!\n')

    const finalRun = demoSteps[9]!.state.run as JsonObject
    expect(finalRun.status).toBe('completed')
    expect(finalRun.reason).toBe('model_final')
    expect(finalRun.model_calls).toBe(3)
    expect(finalRun.tool_calls).toBe(2)
  })
})
