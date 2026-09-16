# Epilog Zing add-on for Rayforge

Ethernet job upload for the **Epilog Zing 24 / Zing 6030**, packaged as a
standalone [Rayforge](https://github.com/barebaric/rayforge) add-on.

Experimental release: vector job upload has been exercised on a Zing with
positive operator feedback. Comprehensive hardware validation remains pending.

## Install

In Rayforge's add-on manager, install from this repository URL:

```text
https://github.com/konglomerat/rayforge-addon-epilog
```

Enable **Epilog Zing**, then restart Rayforge. This add-on requires **add-on
API 21**. It was tested against unmodified Rayforge commit
[`53003000a5dbe27c62c5b93c629b470e9a2bdb3a`](https://github.com/barebaric/rayforge/commit/53003000a5dbe27c62c5b93c629b470e9a2bdb3a).
Compatibility with older stable releases is not implied.

1. Add a machine using the **Epilog Zing 24 (6030)** device profile.
2. Enter your laser's hostname/IP and use port **515**.
3. Check the configured working area. The profile uses the nominal
   **609.6 × 304.8 mm**, with the origin at the **top left**.
4. Import a design, select suitable material settings, and calculate the job.
5. Choose **Upload to Epilog** in the toolbar or Tools menu.
6. Select the uploaded job at the laser and start it using its control panel.

The ordinary Rayforge Send button may remain disabled because the Zing does
not report an idle state. The add-on's upload action checks connection,
calculation, and upload readiness without inventing a machine status. It uses
Rayforge's normal job preparation and preflight checks.

Restart Rayforge after installing, enabling, updating, disabling, or removing
this add-on. Driver registration remains in memory until restart; live driver
unloading is not supported. Existing machines keep their saved driver name.

## Supported behavior

- PJL/PCL/HPGL vector job encoding and Epilog's LPD upload protocol.
- Resolution settings: 100, 200, 250, 400, 500, and 1000 DPI.
- Vector frequency setting: 10–5000.
- Power mapped to the Epilog percentage scale.
- Speed mapped as `cut speed / Maximum Cut Speed × 100`. The profile's
  6000 mm/min reference represents 100%; it is not a calibrated physical
  speed. For example, 600 mm/min represents 10%.
- Curves and Rayforge engraving scan paths converted to linear vector paths.
  This is not native Epilog raster engraving and can produce large jobs.
- Bounds checking in device dots, error reporting, and acknowledged uploads.

Focus/Z motion, autofocus, rotary operation, remote homing/jogging, native
raster engraving, and live machine status are not supported. Focus and air
assist are controlled manually. Start, pause, and stop physical jobs at the
laser. Upload completion means the laser accepted the file, not that cutting
has finished. An interrupted upload is never retried automatically: check the
laser's job list before resending.

The earlier three-height diagnostic used separate experimental commands.
Receipt was acknowledged, but physical Z movement has not been confirmed;
those commands are not included in this release.

## Example

[`examples/rectangle-10mm.svg`](examples/rectangle-10mm.svg) contains a
10 × 10 mm rectangle. It has no material, power, speed, or focus settings.
Choose those in Rayforge for the actual material and inspect placement before
uploading.

## Development and validation

Set up a [Rayforge development checkout](https://github.com/barebaric/rayforge)
with Pixi. From this add-on checkout, run its checks using that environment:

```sh
../Rayforge/.pixi/envs/default/bin/python scripts/check.py --rayforge ../Rayforge
```

The script runs formatting checks, linting, and targeted tests. It reuses
Rayforge's test fixtures and isolates test configuration. Tests exercise
encoding, invalid paths, profile registration, the real contour pipeline,
headless/frontend add-on loading, action readiness, and LPD acknowledgements,
errors, and cancellation against a local fake server. They do not contact a
laser. Validation against an unmodified Rayforge checkout is recommended so
local core changes cannot hide add-on compatibility problems.

Driver registration currently uses Rayforge's Python driver registry because
API 21 declares a machine-registration hook without calling it. The profile
is registered through the startup hook. The upload action uses the add-on
UI action registry. No Rayforge source patch is required at the tested revision.

## Protocol references and license

MIT; see [LICENSE](LICENSE) and [NOTICE](NOTICE).

- [VisiCut](https://github.com/t-oster/VisiCut)
- [LibLaserCut Epilog implementation](https://github.com/t-oster/LibLaserCut/tree/ebe72ea3af3b2ab52d797d8100c635f68722100e/src/main/java/de/thomas_oster/liblasercut/drivers)
- [Epilog Zing manual](https://www.epiloglaser.com/de/assets/downloads/manuals/zing-manual-web.pdf)

LibLaserCut was consulted as a protocol reference; this add-on does not bundle
or depend on its Java implementation. This is a community project, not an
official Epilog product.
