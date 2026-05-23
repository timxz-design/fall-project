# Hardware Sourcing — Per-Home Pilot Kit

_Updated: 15 May 2026 — prices in EUR, EU shipping_

## Per-Home Kit (one pilot installation)

| Item | Qty | Unit price | Vendor | Link |
|------|-----|-----------|--------|------|
| ESP32-S3-DevKitC-1-N8R8 (8 MB flash / 8 MB PSRAM) | 2 | ~€11–14 | Botland (PL) | [Product page](https://botland.store/esp32-wifi-and-bt-modules/26547-esp32-s3-devkitc-1-n8r8-wifi-bluetooth-development-board-with-esp32-s3-wroom-1-chip.html) |
| ESP32-S3-DevKitC-1-N8R8 — alt source | — | similar | TME (PL) | [Product page](https://www.tme.eu/en/details/esp32s3devkc-8r8/development-kits-for-data-transmission/espressif/esp32-s3-devkitc-1-n8r8/) |
| ESP32-S3-DevKitC-1-N8R8 — fast backup | — | varies | Mouser EU | [Product page](https://www.mouser.com/ProductDetail/Espressif-Systems/ESP32-S3-DevKitC-1-N8R8?qs=7D1LtPJG0i2PiuUUKucutQ%3D%3D) |
| Raspberry Pi 5 (4 GB) | 1 | €116.50 | BerryBase (DE) | [Product page](https://www.berrybase.de/en/raspberry-pi-5-4gb-ram) |
| Pi 5 official PSU (27 W USB-C) + active cooler + 32 GB A2 microSD | 1 set | ~€30 | BerryBase | bundle on the same page |
| USB-C cable + 5 V/2 A adapter (for each ESP32) | 2 | ~€8 | Any | — |
| Small project boxes (optional cosmetics) | 2 | ~€4 | Any | skip for first pilot |
| **Per-home total** | | **~€185–200** | | |

### Why Pi 5 over Pi 4

The brief originally suggested a Pi 4 (~€75). After checking current EU stock, **Pi 5 4 GB is only ~€10 more (€116.50 vs €107)** and gives you ~2× the CPU. Worth it once you add heart-rate / breathing / inactivity features that pile more processing onto the same box. If budget is the only driver, Pi 4 (4 GB) at Welectron for €107 is fine for fall-only — but you'll likely regret it when adding features.

### Why N8R8 specifically

The `N8R8` suffix means 8 MB flash + 8 MB PSRAM. RuView's CSI DSP pipeline uses the PSRAM. The cheaper `N8` variant (no PSRAM) will not run the full Tier 2 pipeline. Don't substitute.

## VPS (Cloud Backend)

| Item | Spec | Price | Vendor |
|------|------|-------|--------|
| Hetzner CX22 — Falkenstein or Helsinki | 2 vCPU AMD, 4 GB RAM, 40 GB NVMe, 20 TB traffic | €4–8/mo post-Apr-2026 adjustment | [Hetzner Cloud](https://www.hetzner.com/cloud/) |

## Order Today, Pilot This Week

If you order ESP32s from Botland or TME today (Friday 15 May), they arrive Tuesday at the latest within the EU. BerryBase ships the Pi 5 4 GB next business day (1–3 days quoted). You'll have everything before Day 4 of the plan, which is when integration testing starts.

## Reserve Stock for Pilots 2–5

For the first 5 pilot homes the per-home cost is ~€200 × 5 = €1000 in hardware. If you're confident you'll get to 5 pilots within a month, order 6 of each component now (one spare each) — there's no per-unit volume discount worth waiting for at this scale, and the cost of a delayed install (a customer who lost interest) is far higher than the cost of a spare ESP32 sitting in a drawer.

## What's Deliberately NOT Here

- **Battery backup for the Pi.** Useful eventually, but a power cut in the customer's home means their WiFi is down too — the fall detection wouldn't reach FCM anyway. Add it as a v2 feature once cellular fallback is in.
- **Cellular failover (LTE dongle).** Same reason — out of MVP scope. Twilio SMS fallback (mentioned in the original plan's risk table) is the cheaper bridge for now.
- **Enclosure design.** Use any plastic box for the pilot. Custom enclosures are a brand exercise, not an engineering one.

## Sources

- [BerryBase — Raspberry Pi 5 4 GB](https://www.berrybase.de/en/raspberry-pi-5-4gb-ram)
- [BerryBase — Raspberry Pi 4 4 GB](https://www.berrybase.de/en/raspberry-pi-4-computer-model-b-4gb-ram)
- [Welectron — Raspberry Pi 4 4 GB](https://www.welectron.com/Raspberry-Pi-4-B-4-GB_1)
- [Botland — ESP32-S3-DevKitC-1-N8R8](https://botland.store/esp32-wifi-and-bt-modules/26547-esp32-s3-devkitc-1-n8r8-wifi-bluetooth-development-board-with-esp32-s3-wroom-1-chip.html)
- [TME — ESP32-S3-DevKitC-1-N8R8](https://www.tme.eu/en/details/esp32s3devkc-8r8/development-kits-for-data-transmission/espressif/esp32-s3-devkitc-1-n8r8/)
- [Mouser — ESP32-S3-DevKitC-1-N8R8](https://www.mouser.com/ProductDetail/Espressif-Systems/ESP32-S3-DevKitC-1-N8R8?qs=7D1LtPJG0i2PiuUUKucutQ%3D%3D)
- [Hetzner Cloud pricing 2026](https://costgoat.com/pricing/hetzner)
