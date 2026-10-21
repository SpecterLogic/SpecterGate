import { t } from "./i18n";export const permissionLabels: Record<string, string> = {
  "dashboard.read": t("مشاهده داشبورد"), "users.read": t("مشاهده کاربران"), "users.write": t("ساخت و ویرایش کاربران"), "users.delete": t("حذف کاربران"),
  "subscriptions.read": t("مشاهده گروه‌ها"), "subscriptions.write": t("مدیریت گروه‌ها"), "plans.read": t("مشاهده پلن‌ها"), "plans.manage": t("مدیریت پلن‌ها"),
  "admins.read": t("مشاهده مدیران"), "admins.manage": t("مدیریت مدیران و مجوزها"), "credits.manage": t("مدیریت اعتبار"),
  "nodes.read": t("مشاهده نودها"), "nodes.manage": t("مدیریت نودها"), "inbounds.read": t("مشاهده ورودی‌ها"), "inbounds.manage": t("مدیریت ورودی‌ها"),
  "dns.read": t("مشاهده تونل‌های DNS"), "dns.manage": t("مدیریت تونل‌های DNS"), "xray.manage": t("مدیریت هسته"),
  "settings.read": t("مشاهده تنظیمات"), "settings.manage": t("مدیریت تنظیمات"), "audit.read": t("مشاهده گزارش عملیات"),
  "security.read": t("مشاهده وضعیت Fail2ban"), "security.manage": t("مدیریت Fail2ban و IPهای مسدود"),
  "routing.read": t("مشاهده خروجی‌ها و مسیریابی"), "routing.manage": t("مدیریت خروجی‌ها و مسیریابی")
};
