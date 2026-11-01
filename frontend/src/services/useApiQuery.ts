import { useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { apiOptions } from './queryCache';

export function useApiQuery<T>(path: string, read:(signal:AbortSignal)=>Promise<T>, onSessionExpired:()=>void,
  options: {enabled?:boolean; interval?:number; staleTime?:number} = {}) {
  const query = useQuery({ ...apiOptions(path, read), enabled: options.enabled,
    ...(options.staleTime !== undefined ? { staleTime:options.staleTime } : {}),
    refetchInterval:options.interval, refetchIntervalInBackground:false });
  useEffect(() => {
    if (query.error && 'status' in query.error && query.error.status === 401) onSessionExpired();
  }, [query.error, onSessionExpired]);
  return query;
}
