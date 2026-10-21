import english from '../locales/en.json';
import overrides from '../locales/en-overrides.json';

export const language: 'fa' | 'en' = localStorage.getItem('spectergate-language') === 'en' ? 'en' : 'fa';
export const locale = language === 'en' ? 'en-US' : 'fa-IR';
const catalog: Record<string,string> = {...english,...overrides};
document.documentElement.lang = language;
document.documentElement.dir = language === 'en' ? 'ltr' : 'rtl';
document.title = language === 'en' ? 'SpecterGate | Proxy management' : 'SpecterGate | پنل مدیریت پروکسی';

export function t(value: string): string {
  return language === 'en' ? catalog[value] ?? value : value;
}

export function tt(template: string, values: unknown[]): string {
  return t(template).replace(/\{(\d+)\}/g, (marker, index) => Number(index) < values.length ? String(values[Number(index)] ?? '') : marker);
}

export function setLanguage(value: 'fa' | 'en') {
  localStorage.setItem('spectergate-language',value);
  window.location.reload();
}
