import { describe, expect, it } from 'vitest';
import {
  extractImprovementRecommendationId,
  findImprovementTrialMatch,
  indexImprovementTrialMatches,
  plainImprovementTrialLabel,
} from '@/lib/jarvisImprovementTrial';

describe('extractImprovementRecommendationId', () => {
  it('extracts id from Execute objective stamp', () => {
    expect(
      extractImprovementRecommendationId(
        'Jarvis improvement recommendation [template-insuff-open_orders_empty]: Improve evidence collectors\nRecommended action: …',
      ),
    ).toBe('template-insuff-open_orders_empty');
  });

  it('returns null when stamp is absent', () => {
    expect(extractImprovementRecommendationId('Investigate high swap')).toBeNull();
    expect(extractImprovementRecommendationId('')).toBeNull();
  });
});

describe('plainImprovementTrialLabel', () => {
  it('maps dry-run lifecycle without inventing LAB progress', () => {
    expect(plainImprovementTrialLabel({ taskStatus: 'queued' })).toBe('Queued');
    expect(plainImprovementTrialLabel({ taskStatus: 'waiting_for_approval' })).toBe(
      'Waiting approval',
    );
    expect(plainImprovementTrialLabel({ taskStatus: 'completed' })).toBe('Completed');
    expect(plainImprovementTrialLabel({ taskStatus: 'failed' })).toBe('Failed');
  });

  it('does not claim In LAB when lab_trial is not_started', () => {
    expect(
      plainImprovementTrialLabel({
        taskStatus: 'waiting_for_approval',
        labTrialStatus: 'not_started',
        canSendToLab: false,
      }),
    ).toBe('Waiting approval');
  });

  it('shows Ready for LAB only when Send to LAB is eligible', () => {
    expect(
      plainImprovementTrialLabel({
        taskStatus: 'waiting_for_approval',
        labTrialStatus: 'not_started',
        canSendToLab: true,
      }),
    ).toBe('Ready for LAB');
  });

  it('maps real LAB fields after Send to LAB', () => {
    expect(
      plainImprovementTrialLabel({
        taskStatus: 'sandbox_testing',
        labTrialStatus: 'testing',
      }),
    ).toBe('Testing in LAB');
    expect(
      plainImprovementTrialLabel({
        taskStatus: 'waiting_for_pr_approval',
        labTrialStatus: 'passed',
      }),
    ).toBe('LAB passed');
    expect(
      plainImprovementTrialLabel({
        taskStatus: 'waiting_for_approval',
        labTrialStatus: 'failed',
      }),
    ).toBe('LAB failed');
    expect(
      plainImprovementTrialLabel({
        taskStatus: 'waiting_for_approval',
        labTrialStatus: 'refused',
      }),
    ).toBe('LAB failed');
    expect(
      plainImprovementTrialLabel({
        taskStatus: 'pr_created',
        labTrialStatus: 'promoted',
      }),
    ).toBe('Promoted');
  });
});

describe('findImprovementTrialMatch', () => {
  const recId = 'template-insuff-open_orders_empty';
  const objective = `Jarvis improvement recommendation [${recId}]: Improve evidence collectors`;

  it('matches recommendation id in execution task objective', () => {
    const match = findImprovementTrialMatch(
      recId,
      [
        {
          task_id: 'task-1',
          objective,
          status: 'waiting_for_approval',
          created_at: '2026-08-08T10:00:00Z',
        },
      ],
      [],
    );
    expect(match).toEqual(
      expect.objectContaining({
        taskId: 'task-1',
        label: 'Waiting approval',
      }),
    );
  });

  it('enriches with approval-queue LAB fields and prefers advanced trial', () => {
    const match = findImprovementTrialMatch(
      recId,
      [
        {
          task_id: 'older',
          objective,
          status: 'completed',
          created_at: '2026-08-01T10:00:00Z',
        },
        {
          task_id: 'newer-lab',
          objective,
          status: 'waiting_for_approval',
          created_at: '2026-08-08T12:00:00Z',
        },
      ],
      [
        {
          task_id: 'newer-lab',
          objective,
          status: 'waiting_for_pr_approval',
          can_send_to_lab: false,
          lab_trial_status: 'passed',
          created_at: '2026-08-08T12:00:00Z',
        },
      ],
    );
    expect(match?.taskId).toBe('newer-lab');
    expect(match?.label).toBe('LAB passed');
  });

  it('indexes all recommendation ids present in task feeds', () => {
    const other =
      'Jarvis improvement recommendation [tool-low-utility]: Drop noise collector';
    const map = indexImprovementTrialMatches(
      [
        { task_id: 'a', objective, status: 'queued', created_at: '2026-08-08T10:00:00Z' },
        { task_id: 'b', objective: other, status: 'completed', created_at: '2026-08-08T11:00:00Z' },
      ],
      [],
    );
    expect(map.get(recId)?.label).toBe('Queued');
    expect(map.get('tool-low-utility')?.label).toBe('Completed');
    expect(map.has('missing')).toBe(false);
  });
});
