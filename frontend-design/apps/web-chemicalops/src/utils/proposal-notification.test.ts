import { describe, expect, it } from 'vitest';
import { operationTaskNotificationLink, parseProposalNotificationId, proposalNotificationLink } from './proposal-notification';

describe('提案通知跳转', () => {
  it('仅为提案通知生成通知编号入口', () => {
    expect(proposalNotificationLink({ id: 42, notification_type: 'AI_PROPOSAL_PENDING', related_type: 'AI_ACTION_PROPOSAL' })).toBe('/ai/tasks?proposal_notification=42');
    expect(proposalNotificationLink({ id: 42, notification_type: 'OPERATION_SUGGESTION', related_type: 'AI_ACTION_PROPOSAL' })).toBeUndefined();
    expect(proposalNotificationLink({ id: 42, notification_type: 'AI_PROPOSAL_PENDING', related_type: 'OTHER' })).toBeUndefined();
  });
  it('异常任务通知通过通知编号打开，普通通知不能伪装成任务入口', () => {
    expect(operationTaskNotificationLink({ id: 7, notification_type: 'OPERATION_TASK_ASSIGNED', related_type: 'OPERATION_TASK' })).toBe('/operations/exceptions?task_notification=7');
    expect(operationTaskNotificationLink({ id: 7, notification_type: 'AI_PROPOSAL_PENDING', related_type: 'OPERATION_TASK' })).toBeUndefined();
  });
  it('拒绝伪造、溢出或格式错误的通知编号', () => {
    expect(parseProposalNotificationId('42')).toBe(42);
    for (const input of ['0', '-1', '1e2', '1/2', '9007199254740992', ['1'], undefined]) {
      expect(parseProposalNotificationId(input)).toBeUndefined();
    }
  });
});
