"""Fetch NousResearch's Claude Subscription DirectSDK (Experimental) plugin at a pinned commit.

Usage: python3 fetch-directsdk-plugin.py <output dir>
Only the runtime files are kept, each checked against its sha256 at that commit. The plugin is MIT
licensed (its LICENSE ships alongside). Commit ef73726 is the code the owner's own Hermes runs and is
byte-identical to the reviewed catalog install of plugin version 0.3.0.
"""
import hashlib
import os
import sys
import urllib.request

REPO = "NousResearch/hermes-plugin-claude-subscription-directsdk"
COMMIT = "ef73726cfaf2fa0ee041e55572f406e2c24fed83"
FILES = {
    "LICENSE": "f26e906c042707a257816cf8a0396556b596be540b8add290132b8d72c080d60",
    "README.md": "7884703fc97c07273a3870141eb2480d5bd663fca865bb2df1cf7e90b5e9e77e",
    "plugin.yaml": "13c3e3995d4dbc9b5831758e14bb481d792b7d14b82043c79478f84444d02a20",
    "__init__.py": "0ea1f0a45fd3f8db16bc14fbdaeb6c68c84ed9fd34f97b5c0ea1046dd908f4d2",
    "admission.py": "20500dd7c8f8951a71a8e92206a6d52f0f03d8790c6602b1f80c2f7b5483d0aa",
    "directsdk.py": "36f8bb6bc6e2bd83cd01b26c8e3163592f9a81678928bfcd5eec20f992395f7a",
    "directsdk_setup.py": "0e78787d7771ca83e81c4e2d6f9b224bcf7bae175441c08d7aef2f50864084ab",
    "inert_mcp.py": "bf20a09b2358600981b115c32845ec24722cb66adfc18d247d1c35ed999a0e0a",
    "model_catalog.py": "3cbb588caa3838aa2e5aa9039fc8c52e6f58a84ea80702aa2a413fcd10a34ff7",
}


def main(out: str) -> None:
    os.makedirs(out, exist_ok=True)
    for name, digest in FILES.items():
        url = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{name}"
        data = urllib.request.urlopen(url, timeout=120).read()
        if hashlib.sha256(data).hexdigest() != digest:
            sys.exit(f"sha256 mismatch for {name}")
        with open(os.path.join(out, name), "wb") as fh:
            fh.write(data)
    with open(os.path.join(out, "PINNED_COMMIT"), "w") as fh:
        fh.write(f"https://github.com/{REPO}/tree/{COMMIT}\n")
    print(f"DirectSDK plugin {COMMIT[:12]}: {len(FILES)} files verified")


if __name__ == "__main__":
    main(sys.argv[1])
