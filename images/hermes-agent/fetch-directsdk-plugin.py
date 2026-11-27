"""Fetch NousResearch's Claude Subscription DirectSDK (Experimental) plugin at a pinned commit.

Usage: python3 fetch-directsdk-plugin.py <output dir>
Only the runtime files are kept, each checked against its sha256 at that commit. The plugin is MIT
licensed (its LICENSE ships alongside). It now lives in NousResearch/hermes-official-plugins; commit
968160c is its 0.4.1 release (needs Hermes >= 0.21.4). Since 0.3.3 a tool name Claude was not offered
goes to Hermes, which answers the model with its recoverable unknown-tool error, instead of failing the
whole run with "Native returned a tool outside the current host inventory" (wizard-app-store#92).
"""
import hashlib
import os
import sys
import urllib.request

REPO = "NousResearch/hermes-official-plugins"
COMMIT = "968160cec673d7c41b225e51604cc47048ceca8f"
SUBDIR = "claude-subscription-directsdk"
VERSION = "0.4.1"
FILES = {
    "LICENSE": "f26e906c042707a257816cf8a0396556b596be540b8add290132b8d72c080d60",
    "README.md": "248fa21a4761c907879cf310afd7d632a325611f9fa2cdcc45df8fa7d4e77adf",
    "plugin.yaml": "d668eef764cba95d6940de625ce90013835c17f6c28bd7b69bb50e083a3b8b5b",
    "__init__.py": "34c3201b2eda6b9f9f64cb73d1c61582bd9fd222d3f6406294487d27bf16b0dd",
    "admission.py": "8883d71094d34840701adc0971ce6afb651f9b8f2fdeae44117c364d201b0a32",
    "concurrency.py": "5bd2380f812045b22137de91ab2ac9ba63aa03d4489daf9472504b8772452beb",
    "directsdk.py": "a8ed3cc2b9a2f62328f579f3e0c54799cb18c63e2c8d346550fe2ab2939c859d",
    "directsdk_setup.py": "61ed236fe02476c0f657632d71b2b83c98b2834d5aed809842d06bbe5e00e3e8",
    "extra_usage.py": "945d121a5e7ef3f12f7d4413da71870354d21b3f25539d9f99376da99eabd86d",
    "inert_mcp.py": "bf20a09b2358600981b115c32845ec24722cb66adfc18d247d1c35ed999a0e0a",
    "model_catalog.py": "3862787ddafe2f00d31c9edf9c5be7afe3a0049b67448142c21d184b3da1b2cf",
    "process_tree.py": "1863853948d5d3372b385ec8006a81098c8c77295e66e3d0e030e6d71025c0a3",
}


def main(out: str) -> None:
    os.makedirs(out, exist_ok=True)
    for name, digest in FILES.items():
        url = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{SUBDIR}/{name}"
        data = urllib.request.urlopen(url, timeout=120).read()
        if hashlib.sha256(data).hexdigest() != digest:
            sys.exit(f"sha256 mismatch for {name}")
        with open(os.path.join(out, name), "wb") as fh:
            fh.write(data)
    if f"\nversion: {VERSION}\n" not in open(os.path.join(out, "plugin.yaml")).read():
        sys.exit(f"plugin.yaml is not version {VERSION}")
    with open(os.path.join(out, "PINNED_COMMIT"), "w") as fh:
        fh.write(f"https://github.com/{REPO}/tree/{COMMIT}/{SUBDIR}\n")
    print(f"DirectSDK plugin {VERSION} ({COMMIT[:12]}): {len(FILES)} files verified")


if __name__ == "__main__":
    main(sys.argv[1])
