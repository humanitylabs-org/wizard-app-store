"""Fetch the official native Claude Code binary from npm, pinned and integrity-checked.

Usage: python3 fetch-claude-code.py <amd64|arm64> <output path>
The sha512 values are npm's published `dist.integrity` for each platform package. Kept identical in
images/wizard-ai-accounts and images/hermes-agent (a store test enforces it).
"""
import base64
import hashlib
import io
import os
import sys
import tarfile
import urllib.request

VERSION = "2.1.296"
PACKAGES = {
    "amd64": ("linux-x64", "+m01urgelnI+VJxPaKPEK0wixgq42uZ8PeCaUk5tX/8YoDBvSmC/REVQG2jQfJAr8dxunpjJ600FvLrcj1WWTw=="),
    "arm64": ("linux-arm64", "Q6Qh6qFmwuBG9rQFiDR6bY3XkFnwTN9AAPrnnDgBvr9sbg1Ql5wrf0lfoCDiV369EUHOzxI4i5OdHW9Vf2/oeA=="),
}


def main(arch: str, out: str) -> None:
    platform, integrity = PACKAGES[arch]
    url = (f"https://registry.npmjs.org/@anthropic-ai/claude-code-{platform}/-/"
           f"claude-code-{platform}-{VERSION}.tgz")
    data = urllib.request.urlopen(url, timeout=300).read()
    if base64.b64encode(hashlib.sha512(data).digest()).decode() != integrity:
        sys.exit(f"integrity mismatch for {url}")
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        member = tar.getmember("package/claude")
        handle = tar.extractfile(member)
        if handle is None:
            sys.exit("package/claude is not a regular file")
        binary = handle.read()
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "wb") as fh:
        fh.write(binary)
    os.chmod(out, 0o755)
    print(f"Claude Code {VERSION} {platform}: {len(binary)} bytes")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
