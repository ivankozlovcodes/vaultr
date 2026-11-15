// d3-quadtree 3.0.1 (ISC, https://github.com/d3/d3-quadtree), src/x.js, vendored unmodified except the import paths (relative).
export function defaultX(d) {
  return d[0];
}

export default function(_) {
  return arguments.length ? (this._x = _, this) : this._x;
}
