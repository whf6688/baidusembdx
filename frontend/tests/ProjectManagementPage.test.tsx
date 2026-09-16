import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { ProjectManagementPage } from '../src/features/projects/ProjectManagementPage'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
})

const status = {
  enabled: true,
  running: false,
  status: 'no_changes',
  repository: 'whf6688/baidusembdx',
  repository_url: 'https://github.com/whf6688/baidusembdx.git',
  branch: 'main',
  remote: 'origin',
  remote_verified: true,
  target_branch: 'main',
  next_run_at: '2026-09-17T02:00:00+08:00',
  syncable_count: 0,
  excluded_count: 0,
  ahead_count: 0,
  behind_count: 0,
  last_commit: 'abc1234',
  last_commit_message: 'initial',
  last_finished_at: null,
  summary: '没有需要同步的代码变更。',
  last_error: null,
  conflict_files: [],
}

describe('ProjectManagementPage code sync tile', () => {
  it('shows the ecommerce-style status tile and allows the system owner to start sync', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input)
      const data = url.includes('/runtime-jobs')
        ? { overall_status: 'normal', jobs: [] }
        : status
      return new Response(JSON.stringify({ status: 'ok', data }), {
        status: init?.method === 'POST' ? 202 : 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
    render(<ProjectManagementPage projects={[]} onProjectChange={vi.fn()} projectUrl={() => '#'} writesEnabled canManageCodeSync />)

    expect(await screen.findByRole('heading', { name: '代码同步' })).toBeInTheDocument()
    expect(screen.getByText('main → origin/main')).toBeInTheDocument()
    expect(screen.getByText('没有需要同步的代码变更。')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '立即同步' }))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining('/system/code-sync/run'), expect.objectContaining({ method: 'POST' })))
  })
})
