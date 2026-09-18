# -*- coding: utf-8 -*-
"""把导出的 prices.json 上传到云服务器的插件数据目录。

配合 export_prices.py 用，一条命令搞定「导出 + 上传」：

    python tools/sync_prices.py            # 推荐：导出并上传
    python tools/upload_prices.py          # 只上传已有的 prices.json

凭证从哪来（按优先级，**都不写在仓库里**）
------------------------------------------
1. 命令行参数 `--host/--user/--password`
2. 环境变量 `WOW_DEPLOY_HOST` / `WOW_DEPLOY_USER` / `WOW_DEPLOY_PASSWORD` / `WOW_DEPLOY_KEY`
3. 仓库根目录的 `deploy.json`（已进 .gitignore，格式见下）
4. 交互式输入密码（不回显）

    {"host": "1.2.3.4", "user": "root", "password": "***", "port": 22}

比密码更好的做法是密钥：`ssh-keygen` 之后 `ssh-copy-id root@主机`，
然后 deploy.json 里写 `{"host": "...", "user": "root", "key": "~/.ssh/id_ed25519"}`，
这样密码就不用落盘了。

上传是原子的：先传到同目录下的 `.tmp`，再在服务器上 `mv` 覆盖——
插件随时可能在读这个文件，避免读到写一半的半截 JSON。
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import stat
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
# 凭证文件放 tools/ 或仓库根目录都认（两者都在 .gitignore 里）
DEPLOY_CONF_CANDIDATES = (
    Path(__file__).resolve().parent / "deploy.json",
    REPO_ROOT / "deploy.json",
)

# 插件在服务器上的数据目录（AstrBot 约定）
REMOTE_DIR = "/root/AstrBot/data/plugin_data/astrbot_plugin_wow"
REMOTE_NAME = "prices.json"


def load_conf(args) -> dict:
    """凭证：命令行 > 环境变量 > deploy.json > 交互输入。"""
    conf: dict = {}
    for cand in DEPLOY_CONF_CANDIDATES:
        if not cand.exists():
            continue
        try:
            conf.update(json.loads(cand.read_text(encoding="utf-8")))
        except ValueError as e:
            raise SystemExit(f"{cand} 格式不对：{e}")
        break

    for key, env in (
        ("host", "WOW_DEPLOY_HOST"),
        ("user", "WOW_DEPLOY_USER"),
        ("password", "WOW_DEPLOY_PASSWORD"),
        ("key", "WOW_DEPLOY_KEY"),
        ("port", "WOW_DEPLOY_PORT"),
    ):
        v = os.environ.get(env)
        if v:
            conf[key] = v

    for key in ("host", "user", "password", "key", "port", "remote_dir"):
        v = getattr(args, key, None)
        if v:
            conf[key] = v

    conf.setdefault("user", "root")
    conf.setdefault("port", 22)
    conf.setdefault("remote_dir", REMOTE_DIR)
    conf["port"] = int(conf["port"])

    if not conf.get("host"):
        raise SystemExit(
            "没有主机地址。用 --host 指定，或写进 deploy.json，或设 WOW_DEPLOY_HOST。"
        )
    if not conf.get("key") and not conf.get("password"):
        conf["password"] = getpass.getpass(f"{conf['user']}@{conf['host']} 的密码：")
    return conf


def connect(conf: dict):
    try:
        import paramiko
    except ImportError:
        raise SystemExit("缺少 paramiko，先装：pip install paramiko")

    client = paramiko.SSHClient()
    # 首连自动记住主机指纹；换机器/被中间人时会因指纹变化报错，届时手动确认
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    kwargs = {
        "hostname": conf["host"],
        "port": conf["port"],
        "username": conf["user"],
        "timeout": 20,
        "allow_agent": True,
        "look_for_keys": True,
    }
    key_path = conf.get("key")
    if key_path:
        kwargs["key_filename"] = str(Path(os.path.expanduser(str(key_path))))
    else:
        kwargs["password"] = conf["password"]
        kwargs["look_for_keys"] = False

    client.connect(**kwargs)
    return client


def run(client, cmd: str) -> tuple[int, str, str]:
    _in, out, err = client.exec_command(cmd)
    rc = out.channel.recv_exit_status()
    return rc, out.read().decode("utf-8", "replace"), err.read().decode("utf-8", "replace")


def upload(conf: dict, local: Path) -> None:
    if not local.exists():
        raise SystemExit(
            f"本地没有 {local}。先跑 python tools/export_prices.py 生成，"
            f"或用 tools/sync_prices.py 一步到位。"
        )
    size_mb = local.stat().st_size / 1048576

    # 传之前先确认是能解析的 JSON，别把坏文件推上去
    try:
        with open(local, "r", encoding="utf-8") as f:
            data = json.load(f)
        n_items = len(data.get("items") or [])
        realm = data.get("realm") or "?"
    except (OSError, ValueError) as e:
        raise SystemExit(f"{local} 不是合法的 prices.json（{e}）")
    if not n_items:
        raise SystemExit(f"{local} 里一条物品都没有，不上传")

    remote_dir = conf["remote_dir"].rstrip("/")
    remote = f"{remote_dir}/{REMOTE_NAME}"
    remote_tmp = f"{remote}.tmp"

    print(f"连接 {conf['user']}@{conf['host']}:{conf['port']} …", flush=True)
    client = connect(conf)
    try:
        rc, _, _ = run(client, f"test -d {remote_dir!r}")
        if rc != 0:
            raise SystemExit(
                f"服务器上没有目录 {remote_dir}。确认 AstrBot 路径，或用 --remote-dir 指定。"
            )

        sftp = client.open_sftp()
        try:
            print(f"上传 {local.name}（{size_mb:.2f}MB，{n_items} 条，{realm}）…", flush=True)
            sftp.put(str(local), remote_tmp)
            sftp.chmod(remote_tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0600，只有 root 可读写
        finally:
            sftp.close()

        # 原子覆盖：插件可能正在读旧文件
        rc, _, err = run(client, f"mv -f {remote_tmp!r} {remote!r}")
        if rc != 0:
            run(client, f"rm -f {remote_tmp!r}")
            raise SystemExit(f"服务器上覆盖失败：{err.strip()}")

        rc, out, _ = run(client, f"ls -l {remote!r}")
        print(f"完成：{out.strip()}")
        print("插件下次查询会自动重载（按 mtime 判断），不用重启 AstrBot。")
    finally:
        client.close()


def main() -> None:
    ap = argparse.ArgumentParser(description="上传 prices.json 到云服务器")
    ap.add_argument("-f", "--file", type=Path, default=REPO_ROOT / "prices.json",
                    help="本地 prices.json 路径")
    ap.add_argument("--host")
    ap.add_argument("--user")
    ap.add_argument("--password")
    ap.add_argument("--key", help="私钥路径（比密码更安全）")
    ap.add_argument("--port")
    ap.add_argument("--remote-dir", dest="remote_dir", help=f"默认 {REMOTE_DIR}")
    args = ap.parse_args()

    upload(load_conf(args), args.file)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
