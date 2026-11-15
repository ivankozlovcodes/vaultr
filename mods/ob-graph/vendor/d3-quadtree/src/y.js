// d3-quadtree 3.0.1 (ISC, https://github.com/d3/d3-quadtree), src/y.js, vendored unmodified except the import paths (relative).
export function defaultY(d) {
  return d[1];
}

export default function(_) {
  return arguments.length ? (this._y = _, this) : this._y;
}
