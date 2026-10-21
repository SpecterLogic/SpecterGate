import {language,setLanguage} from '../lib/i18n';
export default function LanguageSelect(){
 return <select className="language-select" aria-label="Language / زبان" value={language} onChange={e=>setLanguage(e.target.value as 'fa'|'en')}><option value="fa">فارسی</option><option value="en">English</option></select>;
}
