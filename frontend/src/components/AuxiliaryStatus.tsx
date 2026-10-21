import {useQuery} from '@tanstack/react-query';
import {api} from '../lib/api';
import {language} from '../lib/i18n';
export default function AuxiliaryStatus(){
 const query=useQuery({queryKey:['auxiliary-status'],queryFn:()=>api.get<{ssh_listeners:number[];ssh_errors:Record<string,string>;mtg_installed:boolean;mtg_running:number[];mtg_errors:Record<string,string>}>('/api/xray/auxiliary/status'),refetchInterval:10000});
 return <div><p>SSH: {query.data?.ssh_listeners.length??0} · MTProto: {query.data?.mtg_running.length??0}</p>{query.data&&!query.data.mtg_installed&&<p>{language==='fa'?'باینری MTG نصب نشده است.':'MTG is not installed.'}</p>}{Object.entries({...query.data?.ssh_errors,...query.data?.mtg_errors}).map(([id,message])=><p role="status" key={id}>#{id}: {message}</p>)}</div>;
}
