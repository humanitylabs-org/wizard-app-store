# Wizard apps for stock Runtipi (generated)

This branch is written by the `Stock store (generated)` workflow on `main` (humanitylabs-org/wizard-os#822). Do not edit it by hand: every run replaces it.

Stock Runtipi reads it as an ordinary app store:

```
https://github.com/humanitylabs-org/wizard-app-store/tree/stock
```

What the generator does for each app the Wizard App Index approves (first-party publishers only):

- fetches the app's own repo at exactly the approved commit and copies its `runtipi/` recipe, `wizard.md`, skill and logo;
- refuses any app that asks for host-level access (privileged, host network, the Docker socket, host paths);
- turns named volumes into folders under the app's data dir (file-backed storage, DECISIONS #79/#80), adds Docker's init for Python servers, and publishes the main port on loopback only;
- maps the Wizard type to Runtipi's fixed categories and raises `tipi_version` whenever the commit changes;
- takes `hermes-agent` at the commit the App Manager's Hermes lock pins today, never newer.

Apps that still need the App Manager fork (source/build packaging, `${APP_SOURCE_DIR}`) are left out; `stock-store.json` names each one and why.
