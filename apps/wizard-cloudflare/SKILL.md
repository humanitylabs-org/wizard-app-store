---
name: wizard-cloudflare
description: "Use when the owner wants to publish a website, back up files, find or buy a domain, change DNS, or asks about Cloudflare (R2 storage, Workers, domains)."
---
# Cloudflare

The owner signs in once in the Cloudflare app; you do everything else. Wizard link: `/wizard-os-home/?open=wizard-cloudflare`. Never ask for, accept or repeat a Cloudflare token or password in chat.

## 0. Always check first
`cloudflare_connection_status`: logins (`connection_id`), their accounts (`account_id`) and `can_change`.
- Nothing connected → say: "Open Cloudflare (/wizard-os-home/?open=wizard-cloudflare) and tap Sign in with Cloudflare. No account? Use Sign up free there, then sign in." Then continue the task yourself once they say they're in (check status again).
- `can_change: false` → for any change, say: "Open Cloudflare and tap Sign in again so I can make changes." Reads still work.
- Several accounts → ask which one, unless the request names it.

## Publish my website
1. The site must be a folder in Files with `index.html` at its root (write it there first with the Files app if you are building the site). Max 2000 files, 25 MB each.
2. `cloudflare_action_prepare` action `site.publish`, payload `{"script": "<name>", "folder": "<path in Files>"}`; add `"single_page": true` for single-page apps. Name: lowercase letters, numbers, dashes. Reusing a name updates that site (the card says "update").
3. Tell the owner in one sentence: "Tap Approve in Cloudflare." Poll `cloudflare_approval_status` (id from step 2) until `succeeded`; `result.url` is the live `https://<name>.<subdomain>.workers.dev` address. Give them that link.
4. Custom domain: show it only if they ask; DNS changes go through `dns.create` (Approve again).

## Back up my files
1. Pick or create a bucket: `cloudflare_resources_read` section `r2`; if none fits, prepare `r2.bucket.create {"name": "wizard-backups"}` and get it approved first.
2. Prepare `r2.backup {"bucket": "...", "folder": "<path in Files>"}` (optional `prefix`; default `YYYY-MM-DD/<folder name>`; a short random tag is added so a backup never overwrites another). Max 500 files, 64 MB each, 512 MB total; split larger folders.
3. Approve → status `succeeded` with `result.prefix` and file count. Note: Cloudflare R2 needs a payment method on the account (free tier still applies); if it fails with that, tell the owner to add one in Cloudflare billing.

## Find / buy a domain
`cloudflare_registrar_search` (ideas) then `cloudflare_registrar_check` (availability + price, 1–20 names). You cannot buy: show name and price, and tell the owner to buy it in Cloudflare (dash.cloudflare.com → Domain Registration). After they buy it, you can publish the site and add DNS.

## Other reads and changes
- `cloudflare_overview`: numbers per account (websites, buckets, bytes stored, domains).
- `cloudflare_resources_read` sections: `r2`, `r2_objects` (+bucket, prefix), `r2_metadata` (+bucket, key), `workers`, `worker` (+script), `zones`, `dns` (+zone id), `account`, `billing` (dashboard link only), `registrations`. Page with `page` (Workers/zones/DNS) or `cursor` (R2/registrations).
- Changes via `cloudflare_action_prepare`: `dns.create {zone_id,type,name,content,ttl?,proxied?}`, `dns.update {+record_id}`, `r2.bucket.create {name}`, `r2.object.put {bucket,key,content_base64,content_type?}`, `workers.deploy {script,main_module,code}`.
- Every change waits for the owner's tap; cancel with `cloudflare_approval_cancel`. Requests expire after an hour.
- Not possible: deleting anything, buying domains, billing, creating accounts.
