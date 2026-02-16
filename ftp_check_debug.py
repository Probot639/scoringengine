#!/usr/bin/env python3
"""Debug helper for FTP scoring checks.

This script mirrors the scorer's FTP behavior:
1) Connect/login
2) Upload a file to a target remote path
3) Download the same file
4) Compare downloaded contents

It prints detailed diagnostics at each step to explain why a check fails.
"""

import argparse
import io
import socket
import sys
import time
from ftplib import FTP, all_errors


def fail(msg: str, code: int = 1) -> int:
    print(f"[FAIL] {msg}")
    return code


def info(msg: str) -> None:
    print(f"[INFO] {msg}")


def ok(msg: str) -> None:
    print(f"[OK] {msg}")


def split_parent(remote_path: str) -> tuple[str, str]:
    clean = remote_path.strip("/")
    if "/" not in clean:
        return ".", clean
    parent, name = clean.rsplit("/", 1)
    return "/" + parent, name


def list_dir(ftp: FTP, remote_parent: str) -> None:
    info(f"Listing parent directory: {remote_parent}")
    lines: list[str] = []
    try:
        ftp.retrlines(f"LIST {remote_parent}", lines.append)
        if lines:
            for line in lines[:20]:
                print(f"  {line}")
        else:
            print("  <empty directory listing>")
    except all_errors as exc:
        print(f"  [WARN] Could not list directory '{remote_parent}': {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug FTP check behavior with detailed output.")
    parser.add_argument("--host", default="10.10.10.36", help="FTP host (default: 10.10.10.36)")
    parser.add_argument("--port", type=int, default=21, help="FTP port (default: 21)")
    parser.add_argument("--user", default="ftpuser", help="FTP username (default: ftpuser)")
    parser.add_argument("--password", default="ftppass123", help="FTP password (default: ftppass123)")
    parser.add_argument(
        "--remote-path",
        default="arasaka_internal/se_probe.txt",
        help="Remote file path to upload/download",
    )
    parser.add_argument("--content", default="SE_FTP_OK", help="Content to write/read-back")
    parser.add_argument("--timeout", type=int, default=10, help="Socket timeout seconds")
    parser.add_argument("--active", action="store_true", help="Use active mode (default is passive)")
    args = parser.parse_args()

    info(f"Target: {args.host}:{args.port}")
    info(f"User: {args.user}")
    info(f"Remote path: {args.remote_path}")
    info(f"Mode: {'active' if args.active else 'passive'}")

    ftp = FTP()
    ftp.set_debuglevel(0)
    ftp.set_pasv(not args.active)
    socket.setdefaulttimeout(args.timeout)

    # 1) Connect/login
    try:
        start = time.time()
        banner = ftp.connect(host=args.host, port=args.port, timeout=args.timeout)
        ok(f"Connected in {time.time() - start:.2f}s")
        info(f"Banner: {banner}")
    except (OSError, TimeoutError, all_errors) as exc:
        return fail(f"Cannot connect to FTP server: {exc}")

    try:
        resp = ftp.login(args.user, args.password)
        ok(f"Authenticated: {resp}")
    except all_errors as exc:
        ftp.close()
        return fail(f"Login failed for '{args.user}': {exc}")

    try:
        pwd = ftp.pwd()
        info(f"Server cwd after login: {pwd}")
    except all_errors as exc:
        print(f"[WARN] Could not read working directory: {exc}")

    remote_parent, remote_name = split_parent(args.remote_path)
    info(f"Parent dir: {remote_parent}, file: {remote_name}")

    try:
        ftp.cwd(remote_parent)
        ok(f"Parent directory exists and is accessible: {remote_parent}")
        try:
            ftp.cwd("/")
        except all_errors:
            pass
    except all_errors as exc:
        list_dir(ftp, "/")
        ftp.quit()
        return fail(f"Parent directory '{remote_parent}' is not accessible: {exc}")

    # 2) Upload
    payload = (args.content + "\n").encode("utf-8")
    info(f"Uploading {len(payload)} bytes to {args.remote_path}")
    try:
        upload_resp = ftp.storbinary(f"STOR {args.remote_path}", io.BytesIO(payload))
        ok(f"Upload response: {upload_resp}")
    except all_errors as exc:
        list_dir(ftp, remote_parent)
        ftp.quit()
        return fail(f"Upload failed (path or permissions): {exc}")

    # 3) Download
    info("Downloading file back for verification")
    downloaded: list[bytes] = []
    try:
        download_resp = ftp.retrbinary(
            f"RETR {args.remote_path}", lambda b: downloaded.append(b)
        )
        ok(f"Download response: {download_resp}")
    except all_errors as exc:
        list_dir(ftp, remote_parent)
        ftp.quit()
        return fail(f"Download failed (path or permissions): {exc}")
    finally:
        try:
            ftp.quit()
        except all_errors:
            ftp.close()

    received = b"".join(downloaded).decode("utf-8", errors="replace")
    expected = args.content + "\n"

    info("----- downloaded content begin -----")
    print(received.rstrip("\n"))
    info("----- downloaded content end -----")

    if received != expected:
        return fail(
            "Content mismatch after roundtrip. "
            f"Expected {expected!r}, got {received!r}",
            code=2,
        )

    ok("Roundtrip successful: upload/download content matched")
    return 0


if __name__ == "__main__":
    sys.exit(main())
