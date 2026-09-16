# Contributing

## Compatibility

The add-on targets Rayforge add-on API 21. Validation used an unmodified
Rayforge checkout at commit
[`53003000a5dbe27c62c5b93c629b470e9a2bdb3a`](https://github.com/barebaric/rayforge/commit/53003000a5dbe27c62c5b93c629b470e9a2bdb3a).
Compatibility with older releases has not been established.

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

## Lifecycle

Restart Rayforge after installing, enabling, updating, disabling, or removing
this add-on. Driver registration remains in memory until restart; live driver
unloading is not supported. Existing machines keep their saved driver name.

## Hardware validation

Vector job upload has been exercised on a Zing with positive operator
feedback. Comprehensive hardware validation remains pending.

A separate three-height diagnostic received upload acknowledgements, but
physical Z movement has not been confirmed. Its experimental commands are
not part of the add-on. Do not treat upload acknowledgements as evidence of
physical motion or completion.

When reporting hardware results, include the machine model, add-on and
Rayforge versions, job settings, and what you observed at the machine.
