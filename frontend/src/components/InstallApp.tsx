import {useEffect,useState} from 'react';
import {language} from '../lib/i18n';
type InstallEvent=Event&{prompt:()=>Promise<void>;userChoice:Promise<{outcome:string}>};
export default function InstallApp(){
 const [prompt,setPrompt]=useState<InstallEvent|null>(null);
 useEffect(()=>{const listener=(event:Event)=>{event.preventDefault();setPrompt(event as InstallEvent);};window.addEventListener('beforeinstallprompt',listener);return()=>window.removeEventListener('beforeinstallprompt',listener);},[]);
 if(!prompt)return null;
 return <button type="button" className="text-link" onClick={async()=>{await prompt.prompt();await prompt.userChoice;setPrompt(null);}}>{language==='fa'?'نصب پنل':'Install panel'}</button>;
}
