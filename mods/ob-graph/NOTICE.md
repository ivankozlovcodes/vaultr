# ob-graph: notices

The Graph panel (`sim.js`, `main.js`) is a port of the graph view in Quartz v4 (https://github.com/jackyzha0/quartz),
at commit `d25a6eab` (package version 4.5.2): `quartz/components/Graph.tsx` (defaults) and
`quartz/components/scripts/graph.inline.ts` (forces, hover, labels, zoom, drag). Its defaults and formulas are used
as data; the drawing is Herdr's own (gpui), not Quartz's Pixi renderer. Vaultr's own changes to the simulation: machines and
spaces push less and machines are drawn gently to the middle; and heavier damping (velocityDecay 0.8, alphaDecay 0.06, drag
heat 0.2 where d3 has 0.4 and 0.0228 and Quartz drags at 1) so the graph is not floaty; node radius grows with the links to a node (base 3, +1.8 x sqrt of its links beyond the first,
capped at 11; Quartz: 2 + sqrt of its links); machines and spaces are drawn as a diamond and a hexagon; agents are coloured by program.

## Quartz (MIT)

MIT License

Copyright (c) 2021 jackyzha0

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## d3-force 3.0.0 and d3-quadtree 3.0.1, d3-dispatch 3.0.1 (ISC)

Vendored in `vendor/` (`src/*.js` from the npm tarballs; the versions Quartz v4.5.2's `package-lock.json` pins).
Each package's `LICENSE` is kept in its folder. Changes from upstream: relative import paths between the vendored
packages, and d3-force's use of d3-timer replaced by an inert stepper (Herdr has no timers; the mod ticks the
simulation). The d3-timer package is not vendored. Every vendored file's first line names its package and version.
