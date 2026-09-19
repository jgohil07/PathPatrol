# Path Patrol

A small browser game inspired by Samsung feature-phone **Space War** and the wider Qix/JezzBall family. Claim 65–70% of the coloured board without allowing a moving patrol to hit a route while it grows.

## Run it

The game is the `site/` folder: plain HTML, CSS and ES modules with no build step. Browsers won't load ES modules from `file://`, so serve it:

```sh
python3 tools/serve.py        # then open http://127.0.0.1:8000/
```

Tests: `make setup` once, then `make test`.

## Controls

- Drag from one point in the coloured field toward another to aim a straight route. On release, it grows in both directions until it reaches safe terrain.
- Use the **Flight / Drive** toggle (or **T**) to switch between planes with mountain/runway visuals and cars with city/road visuals.
- Use **P** or **Escape** to pause.

Level difficulty grows through faster patrols, additional patrols, and internal mountain/city blocks. Records and settings are saved with `localStorage` under the `pathpatrol:v2` key; records from the earlier `color-divide-records-v1` key are migrated (and that key is left alone).
