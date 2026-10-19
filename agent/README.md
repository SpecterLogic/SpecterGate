# SpecterGate Node Agent

عامل سبک نود برای سرورهای راه دور. این برنامه:

1. هر ۶۰ ثانیه ضربان قلب و مصرف CPU/RAM را گزارش می‌کند.
2. کانفیگ مخصوص همان نود را از پنل می‌گیرد.
3. کانفیگ را با `xray run -test` اعتبارسنجی می‌کند.
4. فقط در صورت معتبر بودن، فایل را جایگزین و Xray را ری‌استارت می‌کند.
5. آمار مصرف هر کاربر را از Xray API می‌خواند و به پنل می‌فرستد.

## نصب روی سرور نود (Ubuntu/Debian)

```bash
sudo apt-get update
sudo apt-get install -y python3 curl unzip
mkdir -p /usr/local/share/xray
curl -fsSL https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip -o /tmp/xray.zip
sudo unzip -q /tmp/xray.zip -d /usr/local/share/xray
sudo install -m 0755 /usr/local/share/xray/xray /usr/local/bin/xray

sudo mkdir -p /opt/spectergate-agent /etc/spectergate /var/lib/spectergate-agent
sudo cp spectergate_agent.py /opt/spectergate-agent/
sudo cp agent.env.example /etc/spectergate/agent.env
sudo nano /etc/spectergate/agent.env
```

کلید نود را از صفحهٔ **نودها → راهنمای عامل** کپی کنید و در `SPECTERGATE_NODE_KEY` قرار دهید.

```bash
sudo cp deploy/spectergate-agent.service /etc/systemd/system/spectergate-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now spectergate-agent
sudo journalctl -u spectergate-agent -f
```

پورت‌های اینباندهای تخصیص‌یافته به این نود باید در فایروال و سمت کلود/provider باز باشند. اگر از پورت زیر ۱۰۲۴ استفاده می‌کنید، سرویس باید با root اجرا شود (پیش‌فرض همین است).

> عامل، Xray را خودش اجرا می‌کند. اگر روی سرور یک سرویس Xray جداگانه دارید، ابتدا آن را متوقف کنید تا پورت‌ها تداخل نکنند.
