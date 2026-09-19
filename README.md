# Path Patrol

A small browser game inspired by Samsung feature-phone **Space War** and the wider Qix/JezzBall family. Claim 65–70% of the coloured board without allowing a moving patrol to hit a route while it grows.

## Run it

Open `index.html` in a modern browser. No build step or server is required.

## Controls

- Drag from one point in the coloured field toward another to aim a straight route. On release, it grows in both directions until it reaches safe terrain.
- Use the **Flight / Drive** toggle (or **F** / **D**) to switch between planes with mountain/runway visuals and cars with city/road visuals.
- Use **P** or **Escape** to pause.

Level difficulty grows through faster patrols, additional patrols, and internal mountain/city blocks. Records and the selected visual mode are saved with `localStorage` under the `color-divide-records-v1` key.
