# -*- coding: utf-8 -*-
"""一步到位：解本机 Auctionator 价格库 → 上传到云服务器。

    python tools/sync_prices.py                 # 导出 + 上传
    python tools/sync_prices.py --realm 白银之手
    python tools/sync_prices.py --export-only   # 只导出，不上传

放进 Windows 任务计划程序即可定时同步（游戏登出后写盘才有新数据，
所以按「每天晚上你下线之后」跑一次最合适）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
OUT = REPO_ROOT / "prices.json"


def main() -> int:
    argv = sys.argv[1:]
    export_only = "--export-only" in argv
    passthru = [a for a in argv if a != "--export-only"]

    # 导出参数只认 export_prices 的；上传参数（--host 等）留给第二步
    export_args, upload_args = [], []
    i = 0
    export_flags = {"--realm", "--sv", "--wtf", "-o", "--out"}
    upload_flags = {"--host", "--user", "--password", "--key", "--port", "--remote-dir"}
    while i < len(passthru):
        a = passthru[i]
        head = a.split("=", 1)[0]
        if head in export_flags:
            export_args.append(a)
            if "=" not in a and i + 1 < len(passthru):
                export_args.append(passthru[i + 1])
                i += 1
        elif head in upload_flags:
            upload_args.append(a)
            if "=" not in a and i + 1 < len(passthru):
                upload_args.append(passthru[i + 1])
                i += 1
        elif a == "--refresh-names":
            export_args.append(a)
        else:
            print(f"忽略无法识别的参数：{a}")
        i += 1

    # 子进程直接写终端，父进程的 print 必须 flush，否则两步的标题会错位
    print("=" * 60, flush=True)
    print("第 1 步：导出本机 Auctionator 价格库", flush=True)
    print("=" * 60, flush=True)
    rc = subprocess.call(
        [sys.executable, str(HERE / "export_prices.py"), "-o", str(OUT), *export_args]
    )
    if rc != 0:
        print("\n导出失败，不继续上传。", flush=True)
        return rc

    if export_only:
        print(f"\n--export-only：产物在 {OUT}，没有上传。", flush=True)
        return 0

    print(flush=True)
    print("=" * 60, flush=True)
    print("第 2 步：上传到云服务器", flush=True)
    print("=" * 60, flush=True)
    return subprocess.call(
        [sys.executable, str(HERE / "upload_prices.py"), "-f", str(OUT), *upload_args]
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
