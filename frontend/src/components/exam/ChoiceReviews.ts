import { useEffect, useState } from 'react';
import { OmniStudyAPI } from '../../services/api';
import { ActiveExamSession } from '../../types/assessment';

type Reviews = Record<number, Record<string, string>>;
export function useChoiceReviews(paper: ActiveExamSession | null, visible: boolean) {
  const id = visible ? paper?.session_id : undefined;
  const missing = id ? paper!.questions.filter(q => q.question_type.startsWith('mcq') && !q.option_explanations).map(q => q.id).join(',') : '';
  const [state, setState] = useState<{ id?: number; items: Reviews; failed: boolean }>({items: {}, failed: false});
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!id || !missing) return;
    let active = true;
    setState(prev => ({id, items: prev.id === id ? prev.items : {}, failed: false}));
    const ids = missing.split(',').map(Number);
    const load = async () => {
      for (let i = 0; i < ids.length && active; i += 3) {
        try {
          const items = await OmniStudyAPI.choiceReviews(id, ids.slice(i, i+3));
          if (active) setState(prev => ({...prev, items: {...prev.items, ...items}}));
        } catch {
          if (active) setState(prev => ({...prev, failed: true}));
          break;
        }
      }
    };
    void load();
    return () => { active = false; };
  }, [id, missing, attempt]);
  return { items: state.id === id ? state.items : {}, failed: !!missing && state.id === id && state.failed, retry: () => setAttempt(n => n+1) };
}
