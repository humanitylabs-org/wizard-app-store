"""Fetch the holographic memory provider plugin at the commit Hermes' own plugin catalog pins.

Usage: python3 fetch-holographic-plugin.py <output dir>
Hermes v0.22+ no longer ships the holographic memory provider in core: it became the community catalog
plugin itpartypattaya/hermes-plugin-holographic, which Hermes downloads from GitHub the first time an
agent with `memory.provider: holographic` starts. Every agent the Agent Service creates uses it, so
without this an agent starts with no memory when it has no internet and pulls third-party code at
startup when it has (wizard-app-manager#856, James chose to build it in). This keeps the runtime files
of the commit v0.23.3's in-tree catalog pins (plugin-catalog/holographic.yaml: ed73195, version 0.30.0),
each checked against its sha256. The Dockerfile puts them where the provider lived in core
(plugins/memory/holographic), with the same provider name, so Hermes finds it bundled and never tries to
install it. MIT licensed (its LICENSE and the bundled dictionaries' licences ship alongside).
NumPy is not added: the plugin treats it as optional (recall goes on by words), exactly as the old
in-core provider ran in the v2026.9.24 engine, which had no NumPy either.
"""
import hashlib
import os
import sys
import urllib.request

REPO = "itpartypattaya/hermes-plugin-holographic"
COMMIT = "ed73195df846913d34f4aea54335718e56d841fb"
VERSION = "0.30.0"
FILES = {
    "__init__.py": "344a8f07ec2c140647fee6f9daffe5036541744f100b253d05d87c737aa056a5",
    "embeddings.py": "6dc7bfe1efb3db03420c6b75c12f6bfe37d559e7549441a2659fe0229e533e7f",
    "entities.py": "c1316e01a6b19af129e78e3e6938303d09a3d4e187f569ac19839be8685e4336",
    "entity_names.py": "6825a8efa82b8ad5db0b6a9473cf124eb05fe9844bb5fb62d5d55853535365e0",
    "experience.py": "d81ae6ba055f1683ab85d502f4d8f4e5b7092735e40b1627a40102cfe1d582a8",
    "graph.py": "fc14672e7f99db512b7b474e242f21d988ac4f07b7c447405fcd682dc3b25de5",
    "history.py": "445596bd77ca5c9ad1ef1410e900a846624b5ed2976f3f78c0dcab8647e7d58a",
    "holographic.py": "8efce5b00a036c353aa79f37c400daa6abbba19c2b89c3e3d80a17071a7a3a16",
    "memory_map.py": "28bf33afc6ace89607d3ff5077a1e48354ba4f934985b5f9d2828975ee26f7a6",
    "net.py": "c47cf22beac0046014e324bc4bf829f2b6bec1424dbfbf56082f266d47ced118",
    "rerank.py": "4d22486c516cb4da1cdedbfac3ecff2481135b4590d9c4b430bda613ffd6986e",
    "retrieval.py": "223dcfce1fc7f6011f121175a4858d216f2e3f8bec0ea2ccd7384ef221e45fa0",
    "screen.py": "49a8aa20adf651af5f3f7858a2c3aff364fb156fa47ef82c174c2666f5426183",
    "store.py": "e92f2ab4aac932de7c3125d16b870f2648157dca43e9388236418b35d88a8797",
    "text.py": "7f28f7d4a060087bba76a59ed3076ce328e02770d2770be78521077fe227084b",
    "plugin.yaml": "b0f655591aab9b6ab35d8c9867846c92e09b844d2e9d211afddd3d2b2c53171e",
    "pyproject.toml": "054da7fd52e432bd0e8c38a29fb55ddf49363ada40bccda7accfadaea3ca7ad6",
    "README.md": "7f976f61ceecb3b9189638d2a27a4d360527a8b7aab76fb56a089fcdb0aee31c",
    "LICENSE": "f76529e417b218b5e2b4794acf1513ce205c35dad6e1947e52e7f13e56a76fbb",
    "LICENSES/DerivBase.Ru-Apache-2.0.txt": "df315f481523b8c620a38dba5b44eef01305d1624464f8eb9e9ab9f4e37b2474",
    "LICENSES/OEWN-CC-BY-4.0.md": "672cc8b5663e8dc74c4b07a9dcf477193853575b119908fd3dc0aeeb60a9dbbb",
    "LICENSES/OEWN-WNDB-License.txt": "91d04ca42cbf41b36d381d4cba58c313962f8e16a7a5c93482c2168b23889514",
    "LICENSES/OpenCC-Apache-2.0.txt": "b534e465949558eec2597b04f5092b5e161236a68dfbfd04d547592ac3964308",
    "LICENSES/SudachiDict-Apache-2.0.txt": "dc3b3c3acf9b7d5395fa93216d467bfca0aba203f8316c4044b2e46f64487d54",
    "LICENSES/Wikidata-CC0.txt": "ebb9caeda03769cc5aae0c7ed84986a4dfedb2a369da67587249bf086666e838",
    "LICENSES/jieba-MIT.txt": "49b671f4e451c66b348bea9deb4a81f02ca4a6828b8d67d9635c4eebe90b0d9d",
    "dictionaries/__init__.py": "3e9a1983c444152cb77647dca09f7134e93cefea50f34c7ba25beb1d8e04af57",
    "dictionaries/cjk_fold.py": "890af500da0b68beb6cc215de0e42db6094cdc7da7277ba5e183e2927fc3515a",
    "dictionaries/de_compounds.tsv.gz": "942c854bde407b2bf3912c12eac6aba0dc44c1f3d023f940e80e2b1a93c571e3",
    "dictionaries/de_es_forms.tsv.gz": "3f0f6be5149e57d77534aad07fa50429ca3dce60c231dfc779be677aab4b93ec",
    "dictionaries/en_derivation.tsv.gz": "68c4870ade876fdf89159cad94a52f13150d259a17c677eae1bf959672c81eef",
    "dictionaries/ja_variants.tsv.gz": "5a12dbe68f8518490c1c5ebec552fad785321246e0fc24979d74e93443b2e28c",
    "dictionaries/ru_derivation.tsv.gz": "d1000221d8fd7658470ea116db9c77d8419e39af6d1bbe8405c3a4d6ab8832fc",
    "dictionaries/zh_words.txt.gz": "bcda7c821f8d00d030b8e797da5d3f8868a8b8a2ca9da7bb7d558811ad3cd9e7",
}


def main(out: str) -> None:
    for name, digest in FILES.items():
        url = f"https://raw.githubusercontent.com/{REPO}/{COMMIT}/{name}"
        data = urllib.request.urlopen(url, timeout=120).read()
        if hashlib.sha256(data).hexdigest() != digest:
            sys.exit(f"sha256 mismatch for {name}")
        path = os.path.join(out, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
    if f"\nversion: {VERSION}\n" not in open(os.path.join(out, "plugin.yaml")).read():
        sys.exit(f"plugin.yaml is not version {VERSION}")
    with open(os.path.join(out, "PINNED_COMMIT"), "w") as fh:
        fh.write(f"https://github.com/{REPO}/tree/{COMMIT}\n")
    print(f"holographic memory plugin {VERSION} ({COMMIT[:12]}): {len(FILES)} files verified")


if __name__ == "__main__":
    main(sys.argv[1])
