/** React Query hooks for the scoped reads. Keys start with the page name so the SSE listener can refetch by name. */
import { useQuery } from '@tanstack/react-query';
import { api, scoped } from './client';
import type { CampaignRow, Experiments, Files, Hypotheses, Inbox, Messages, Monitor, Summary, Thread, Threads, WorkspaceInfo } from './types';

const KEEP = { staleTime: 5000, refetchOnWindowFocus: false } as const;

export function useWorkspace() { return useQuery({ queryKey: ['workspace'], queryFn: () => api<WorkspaceInfo>('/api/v1/workspace'), staleTime: 60000 }); }
export function useCampaigns() { return useQuery({ queryKey: ['campaigns'], queryFn: () => api<{ campaigns: CampaignRow[] }>('/api/v1/campaigns').then(body => body.campaigns), ...KEEP }); }
export function useSummary(campaignId: string | null) {
  return useQuery({ queryKey: ['summary', campaignId], enabled: !!campaignId, queryFn: () => api<Summary>(`/api/v1/campaigns/${campaignId}/summary`), ...KEEP });
}
export function useThread(threadId: string | null) {
  return useQuery({ queryKey: ['thread', threadId], enabled: !!threadId, queryFn: () => api<Thread>(`/api/v1/threads/${threadId}`), staleTime: 60000, retry: false });
}
export function useThreads(campaignId: string | null) {
  return useQuery<Threads>({ queryKey: ['threads', campaignId], enabled: !!campaignId, ...KEEP,
    queryFn: ({ client }) => scoped<Threads>(`/api/v1/campaigns/${campaignId}/threads`, client.getQueryData<Threads>(['threads', campaignId])) });
}
export function useMessages(threadId: string | null) {
  return useQuery<Messages>({ queryKey: ['messages', threadId], enabled: !!threadId, ...KEEP,
    queryFn: ({ client }) => scoped<Messages>(`/api/v1/threads/${threadId}/messages`, client.getQueryData<Messages>(['messages', threadId])) });
}
export function useExperiments(campaignId: string | null) {
  return useQuery<Experiments>({ queryKey: ['experiments', campaignId], enabled: !!campaignId, ...KEEP,
    queryFn: ({ client }) => scoped<Experiments>(`/api/v1/campaigns/${campaignId}/experiments`, client.getQueryData<Experiments>(['experiments', campaignId])) });
}
export function useHypotheses(campaignId: string | null) {
  return useQuery<Hypotheses>({ queryKey: ['hypotheses', campaignId], enabled: !!campaignId, ...KEEP,
    queryFn: ({ client }) => scoped<Hypotheses>(`/api/v1/campaigns/${campaignId}/hypotheses`, client.getQueryData<Hypotheses>(['hypotheses', campaignId])) });
}
export function useInbox(campaignId: string | null) {
  return useQuery<Inbox>({ queryKey: ['inbox', campaignId], enabled: !!campaignId, ...KEEP,
    queryFn: ({ client }) => scoped<Inbox>(`/api/v1/campaigns/${campaignId}/inbox`, client.getQueryData<Inbox>(['inbox', campaignId])) });
}
export function useMonitor(campaignId: string | null) {
  return useQuery<Monitor>({ queryKey: ['monitor', campaignId], enabled: !!campaignId, ...KEEP, refetchInterval: 15000,
    queryFn: ({ client }) => scoped<Monitor>(`/api/v1/campaigns/${campaignId}/monitor`, client.getQueryData<Monitor>(['monitor', campaignId])) });
}
export function useFiles(campaignId: string | null) {
  return useQuery<Files>({ queryKey: ['files', campaignId], enabled: !!campaignId, ...KEEP,
    queryFn: ({ client }) => scoped<Files>(`/api/v1/campaigns/${campaignId}/files`, client.getQueryData<Files>(['files', campaignId])) });
}
export function useRead<T>(key: unknown[], path: string | null, options: { refetchInterval?: number; staleTime?: number } = {}) {
  return useQuery<T>({ queryKey: key, enabled: !!path, queryFn: () => api<T>(path as string), staleTime: options.staleTime ?? 5000, refetchOnWindowFocus: false, refetchInterval: options.refetchInterval });
}
